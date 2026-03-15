"""
Base collector 모듈 - 모든 수집기의 기본 인터페이스
"""

import logging
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from priceradar.resilience import SourceCircuitBreakerManager
from priceradar.validators import (
    validate_discount_rate,
    validate_price_range,
    validate_url_format,
)


logger = logging.getLogger(__name__)
_DEFAULT_HEALTH_DB_PATH = "data/radar_data.duckdb"


def _load_adaptive_controls() -> tuple[type[Any], type[Any]]:
    module = __import__("radar_core", fromlist=["AdaptiveThrottler", "CrawlHealthStore"])
    return module.AdaptiveThrottler, module.CrawlHealthStore


@dataclass
class RawItem:
    """수집한 원시 데이터 아이템"""

    product_id: str
    title: str
    url: str
    source: str
    collected_at: datetime = field(default_factory=datetime.now)

    current_price: int | None = None
    avg_price: int | None = None
    list_price: int | None = None
    discount_rate: float | None = None

    category: str | None = None
    platform: str | None = None
    image_url: str | None = None
    brand: str | None = None

    is_hotdeal: bool = False
    is_popular: bool = False
    is_lowest_now: bool = False

    raw_data: dict[str, Any] = field(default_factory=dict)


class BaseCollector(ABC):
    """모든 수집기의 기본 클래스"""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        self.source_id = source_id
        self.config = config
        self.breaker_manager = SourceCircuitBreakerManager()
        self._session = self._create_session()
        self.rate_limit = float(self.config.get("rate_limit", 1.0))
        self._last_request: float = 0.0
        self._lock: threading.Lock = threading.Lock()
        throttler_cls, health_store_cls = _load_adaptive_controls()
        self._throttler = throttler_cls(
            min_delay=max(0.001, float(self.config.get("rate_limit", 1.0)))
        )
        self._health_store = health_store_cls(
            os.environ.get("RADAR_CRAWL_HEALTH_DB_PATH", _DEFAULT_HEALTH_DB_PATH)
        )

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[408, 429, 500, 502, 503, 504, 522, 524],
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _apply_rate_limit(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
            self._last_request = time.monotonic()

    def _fetch_with_retry(self, url: str) -> requests.Response:
        max_attempts = 3
        source_name = self._resolve_source_name() or (urlparse(url).netloc or self.source_id)
        retryable_errors = (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
        )

        for attempt in range(max_attempts):
            self._apply_rate_limit()
            self._throttler.acquire(source_name)

            try:
                response = self._session.get(url, timeout=self._resolve_timeout())
                if response.status_code in (408, 429, 500, 502, 503, 504, 522, 524):
                    logger.warning(
                        "Retryable HTTP status %s for %s, will retry",
                        response.status_code,
                        url,
                    )
                    response.raise_for_status()
                response.raise_for_status()

                self._throttler.record_success(source_name)
                delay = self._throttler.get_current_delay(source_name)
                self._health_store.record_success(source_name, delay)
                return response
            except retryable_errors as exc:
                retry_after: int | str | None = None
                if isinstance(exc, requests.exceptions.HTTPError):
                    response = exc.response
                    if response is not None and response.status_code == 429:
                        retry_after = _parse_retry_after(response.headers.get("Retry-After"))

                self._throttler.record_failure(source_name, retry_after=retry_after)
                delay = self._throttler.get_current_delay(source_name)
                self._health_store.record_failure(source_name, str(exc), delay)

                if attempt == max_attempts - 1:
                    raise

        raise RuntimeError("Retry loop exited unexpectedly")

    def _resolve_source_name(self) -> str:
        source_name = self.config.get("name")
        if isinstance(source_name, str) and source_name:
            return source_name
        return self.source_id

    def _resolve_timeout(self) -> float:
        timeout = self.config.get("timeout", 30)
        if isinstance(timeout, (int, float)):
            return float(timeout)
        return 30.0

    def _fetch(self, url: str) -> requests.Response:
        source_name = self._resolve_source_name()
        breaker = self.breaker_manager.get_breaker(source_name)
        return breaker.call(
            lambda source=source_name: self._fetch_with_retry(url),
            source=source_name,
        )

    def _fetch_html(self, url: str) -> str | None:
        source_name = self._resolve_source_name()
        breaker = self.breaker_manager.get_breaker(source_name)

        def _fetch_html_impl() -> str | None:
            response = self._fetch_with_retry(url)
            response.encoding = response.apparent_encoding or "utf-8"
            return response.text

        return breaker.call(
            lambda source=source_name: _fetch_html_impl(),
            source=source_name,
        )

    def _fetch_json(self, url: str) -> dict[str, Any] | list[Any]:
        source_name = self._resolve_source_name()
        breaker = self.breaker_manager.get_breaker(source_name)

        def _fetch_json_impl() -> dict[str, Any] | list[Any]:
            response = self._fetch_with_retry(url)
            return response.json()

        return breaker.call(
            lambda source=source_name: _fetch_json_impl(),
            source=source_name,
        )

    def __del__(self) -> None:
        self._session.close()
        self._health_store.close()

    @abstractmethod
    def collect(self) -> list[RawItem]:
        """데이터를 수집하고 RawItem 리스트를 반환"""
        pass

    def validate_item(self, item: RawItem) -> bool:
        # 필수 필드 검증
        if not item.product_id or not item.title or not item.url:
            return False

        # URL 형식 검증
        if not validate_url_format(item.url):
            return False

        # 가격 범위 검증 (None 허용 - 선택적 필드)
        if item.current_price is not None and not validate_price_range(item.current_price):
            return False

        if item.avg_price is not None and not validate_price_range(item.avg_price):
            return False

        if item.list_price is not None and not validate_price_range(item.list_price):
            return False

        # 할인율 검증 (None 허용)
        if item.discount_rate is not None and not validate_discount_rate(item.discount_rate):
            return False

        return True

    def _validate_html_schema(
        self,
        soup: BeautifulSoup | Tag,
        required_selectors: Mapping[str, str],
        *,
        context: str,
    ) -> bool:
        missing: list[dict[str, str]] = []
        for label, selector in required_selectors.items():
            cleaned = selector.strip()
            if not cleaned:
                continue
            if soup.select_one(cleaned) is None:
                missing.append({"element": str(label), "selector": cleaned})

        if missing:
            logger.warning(
                "html_schema_validation_failed source_id=%s context=%s missing=%s",
                self.source_id,
                context,
                missing,
            )
            return False

        return True

    def _parse_price_value(self, value: Any) -> int | None:
        if value is None:
            return None

        if isinstance(value, bool):
            return None

        if isinstance(value, int):
            return value if value > 0 else None

        if isinstance(value, float):
            if value <= 0:
                return None
            return int(value)

        text = str(value).strip()
        if not text:
            return None

        normalized = text.lower()
        if normalized in {"n/a", "na", "none", "null", "nan", "-", "--"}:
            return None

        cleaned = normalized.replace("원", " ")
        cleaned = re.sub(r"[₩￦$€£¥]", " ", cleaned)
        cleaned = cleaned.replace(",", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        matched = re.search(r"\d+(?:\.\d+)?", cleaned)
        if not matched:
            return None

        try:
            parsed = int(float(matched.group(0)))
        except ValueError:
            return None

        return parsed if parsed > 0 else None


def _parse_retry_after(value: str | None) -> int | str | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if stripped.isdigit():
        return int(stripped)

    return stripped
