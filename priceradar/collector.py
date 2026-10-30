from __future__ import annotations

import html
import os
import threading
import time
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests
import structlog
from pybreaker import CircuitBreakerError
from radar_core.dates import parse_feed_entry, resolve_default_timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .collection_contract import (
    PRICERADAR_USER_AGENT,
    REQUEST_TIMEOUT_SECONDS,
    is_challenge_or_error_page,
)
from .exceptions import NetworkError, ParseError, SourceError
from .models import Article, Source
from .resilience import get_circuit_breaker_manager


logger = structlog.get_logger()


_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": PRICERADAR_USER_AGENT,
}
_DEFAULT_HEALTH_DB_PATH = "data/radar_data.duckdb"
_COLLECTION_CONTROL_LOCK = threading.Lock()
_ACTIVE_THROTTLER: Any | None = None
_ACTIVE_HEALTH_STORE: Any | None = None


def _load_adaptive_controls() -> tuple[type[Any], type[Any]]:
    module = __import__("radar_core", fromlist=["AdaptiveThrottler", "CrawlHealthStore"])
    return module.AdaptiveThrottler, module.CrawlHealthStore


def _set_collection_controls(throttler: Any, health_store: Any) -> None:
    global _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE
    with _COLLECTION_CONTROL_LOCK:
        _ACTIVE_THROTTLER = throttler
        _ACTIVE_HEALTH_STORE = health_store


def _clear_collection_controls() -> None:
    global _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE
    with _COLLECTION_CONTROL_LOCK:
        _ACTIVE_THROTTLER = None
        _ACTIVE_HEALTH_STORE = None


def _get_collection_controls() -> tuple[Any | None, Any | None]:
    with _COLLECTION_CONTROL_LOCK:
        return _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE


class RateLimiter:
    def __init__(self, min_interval: float = 0.5):
        self._min_interval: float = min_interval
        self._last_request: float = 0.0
        self._lock: threading.Lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()


def _resolve_max_workers(max_workers: int | None = None) -> int:
    if max_workers is None:
        raw_value = os.environ.get("RADAR_MAX_WORKERS", "5")
        try:
            parsed = int(raw_value)
        except ValueError:
            parsed = 5
    else:
        parsed = max_workers

    return max(1, min(parsed, 10))


def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_DEFAULT_HEADERS)

    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = PRICERADAR_USER_AGENT
    session.verify = True

    return session


def _fetch_url_with_retry(
    url: str,
    timeout: int,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
    source_name: str | None = None,
    throttler: Any | None = None,
    health_store: Any | None = None,
    max_attempts: int = 3,
) -> requests.Response:
    """Fetch URL with retry logic on transient errors."""
    merged = {**_DEFAULT_HEADERS, **(headers or {})}
    merged["User-Agent"] = PRICERADAR_USER_AGENT
    if throttler is None or health_store is None:
        active_throttler, active_health_store = _get_collection_controls()
        throttler = throttler or active_throttler
        health_store = health_store or active_health_store

    retryable_errors = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    )

    for attempt in range(max_attempts):
        if source_name is not None and throttler is not None:
            throttler.acquire(source_name)

        try:
            if session is not None:
                response = session.get(url, timeout=timeout, headers=merged, verify=True)
            else:
                response = requests.get(url, timeout=timeout, headers=merged, verify=True)
            response.raise_for_status()

            if source_name is not None and throttler is not None:
                throttler.record_success(source_name)
                if health_store is not None:
                    delay = throttler.get_current_delay(source_name)
                    health_store.record_success(source_name, delay)

            return response
        except retryable_errors as exc:
            if source_name is not None and throttler is not None:
                retry_after: int | str | None = None
                if isinstance(exc, requests.exceptions.HTTPError):
                    response = exc.response
                    if response is not None and response.status_code == 429:
                        retry_after = _parse_retry_after(response.headers.get("Retry-After"))

                throttler.record_failure(source_name, retry_after=retry_after)
                if health_store is not None:
                    delay = throttler.get_current_delay(source_name)
                    health_store.record_failure(source_name, str(exc), delay)

            if attempt == max_attempts - 1:
                raise

    raise RuntimeError("Retry loop exited unexpectedly")


def _parse_retry_after(value: str | None) -> int | str | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if stripped.isdigit():
        return int(stripped)

    return stripped


def collect_sources(
    sources: list[Source],
    *,
    category: str,
    limit_per_source: int = 30,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    min_interval_per_host: float = 0.5,
    max_workers: int | None = None,
    health_db_path: str | None = None,
) -> tuple[list[Article], list[str]]:
    """Fetch items from all configured sources, returning articles and errors.

    Uses a 2-pass hybrid collection strategy:

    * **Pass 1** — RSS/feed sources collected in parallel via
      :class:`~concurrent.futures.ThreadPoolExecutor`.
    * **Pass 2** — JavaScript/browser sources collected sequentially via
      Playwright (see :mod:`priceradar.browser_collector`).

    If Playwright is not installed, JS sources are silently skipped with a
    warning log entry so that RSS-only mode keeps working.
    """
    # --- Source splitting ---------------------------------------------------
    rss_sources = [s for s in sources if s.type.lower() not in ("javascript", "browser")]
    js_sources = [s for s in sources if s.type.lower() in ("javascript", "browser")]

    articles: list[Article] = []
    errors: list[str] = []
    manager = get_circuit_breaker_manager()
    workers = _resolve_max_workers(max_workers)
    source_hosts: dict[str, str] = {
        source.name: (urlparse(source.url).netloc.lower() or source.name) for source in rss_sources
    }
    rate_limiters: dict[str, RateLimiter] = {
        host: RateLimiter(min_interval=min_interval_per_host) for host in set(source_hosts.values())
    }
    throttler_cls, health_store_cls = _load_adaptive_controls()
    throttler = throttler_cls(min_delay=max(0.001, min_interval_per_host))
    health_store = health_store_cls(
        health_db_path or os.environ.get("RADAR_CRAWL_HEALTH_DB_PATH", _DEFAULT_HEALTH_DB_PATH)
    )
    _set_collection_controls(throttler, health_store)
    session = _create_session()

    def _collect_for_source(source: Source) -> tuple[list[Article], list[str]]:
        if health_store.is_disabled(source.name):
            return [], [f"{source.name}: Source disabled (crawl health threshold reached)"]

        host = source_hosts[source.name]
        rate_limiters[host].acquire()

        try:
            breaker = manager.get_breaker(source.name)
            result = breaker.call(
                _collect_single,
                source,
                category=category,
                limit=limit_per_source,
                timeout=timeout,
                session=session,
            )
            return result, []
        except CircuitBreakerError:
            return [], [f"{source.name}: Circuit breaker open (source unavailable)"]
        except SourceError as exc:
            return [], [str(exc)]
        except (NetworkError, ParseError) as exc:
            return [], [f"{source.name}: {exc}"]
        except Exception as exc:
            return [], [f"{source.name}: Unexpected error - {type(exc).__name__}: {exc}"]

    # --- Pass 1: RSS sources via ThreadPoolExecutor (parallel) --------------
    try:
        if workers == 1:
            for source in rss_sources:
                source_articles, source_errors = _collect_for_source(source)
                articles.extend(source_articles)
                errors.extend(source_errors)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map: list[Future[tuple[list[Article], list[str]]]] = [
                    executor.submit(_collect_for_source, source) for source in rss_sources
                ]

                for future in future_map:
                    source_articles, source_errors = future.result()
                    articles.extend(source_articles)
                    errors.extend(source_errors)
    finally:
        session.close()
        health_store.close()
        _clear_collection_controls()

    # --- Pass 2: JavaScript/browser sources via Playwright (sequential) -----
    if js_sources:
        try:
            from .browser_collector import collect_browser_sources

            js_articles, js_errors = collect_browser_sources(
                js_sources, category, health_db_path=health_db_path
            )
            articles.extend(js_articles)
            if js_errors:
                logger.warning("browser_collection_errors", errors=js_errors)
        except ImportError:
            logger.warning(
                "playwright_unavailable",
                js_source_count=len(js_sources),
                hint="pip install 'radar-core[browser]'",
            )

    return articles, errors


def _collect_single(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    if source.type.lower() != "rss":
        raise SourceError(source.name, f"Unsupported source type '{source.type}'")

    try:
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        raise NetworkError(f"Network error fetching {source.name}: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise SourceError(source.name, f"Request failed: {exc}", exc) from exc

    try:
        feed = feedparser.parse(response.content)
        feed_meta = getattr(feed, "feed", {}) or {}
        feed_title = str(feed_meta.get("title") or "") if isinstance(feed_meta, Mapping) else ""
        preview = response.text[:4000] if isinstance(getattr(response, "text", None), str) else ""
        if is_challenge_or_error_page(feed_title, preview):
            return []

        items: list[Article] = []

        for entry in feed.entries[:limit]:
            published, published_raw = _extract_published(entry, source)
            summary = _entry_text(entry, "summary") or _entry_text(entry, "description")
            if not summary:
                _content = entry.get("content", [])
                if isinstance(_content, list) and _content:
                    first_item = _content[0]
                    if isinstance(first_item, Mapping):
                        value = first_item.get("value")
                        if isinstance(value, str):
                            summary = value

            title = html.unescape(_entry_text(entry, "title").strip()) or "(no title)"
            summary_text = html.unescape(summary.strip())
            if is_challenge_or_error_page(title, summary_text):
                continue
            items.append(
                Article(
                    title=title,
                    link=_entry_text(entry, "link").strip(),
                    summary=summary_text,
                    published=published,
                    source=source.name,
                    category=category,
                    published_raw=published_raw,
                )
            )

        return items
    except Exception as exc:
        raise ParseError(f"Failed to parse feed from {source.name}: {exc}") from exc


def _extract_datetime(entry: Mapping[str, Any], source: Source | None = None) -> datetime | None:
    """Parse a feed entry date. Prefer :func:`_extract_published` for the raw string."""
    return _extract_published(entry, source)[0]


def _extract_published(
    entry: Mapping[str, Any], source: Source | None = None
) -> tuple[datetime | None, str | None]:
    """Parse ``*_parsed`` as UTC and zone-less strings in the source timezone.

    feedparser structs are UTC. ``calendar.timegm`` (via radar-core) keeps that
    instant. ``time.mktime`` would read them as local time and, under
    ``TZ=Asia/Seoul``, store the instant nine hours early.
    """
    default_timezone = "UTC"
    if source is not None:
        default_timezone = resolve_default_timezone(
            source_url=source.url,
            default_timezone=source.default_timezone,
            config=source.config,
        )
    return parse_feed_entry(entry, default_timezone=default_timezone)


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value if isinstance(value, str) else ""
