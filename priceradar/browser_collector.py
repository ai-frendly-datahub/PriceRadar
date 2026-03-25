"""Browser-based article collection for JavaScript-rendered sources.

PriceRadar adaptation of the standard 2-pass hybrid collection pattern.

Design:
    Pass 1 (collector.py): RSS/feed sources -> ThreadPoolExecutor (parallel)
    Pass 2 (this module):  JS/browser sources -> Playwright (sequential)

Playwright is an optional dependency.  If ``radar-core[browser]`` is not
installed, this module degrades gracefully -- returning empty results with
a descriptive error string so the caller can log a warning and continue.

Note: PriceRadar also has its own registry-based BrowserCollector at
``priceradar.collectors.browser_collector`` for the CollectorRegistry
pipeline.  This module provides the *standard-tier interface* used by
``collector.py``'s 2-pass logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from .models import Article


if TYPE_CHECKING:
    from .models import Source

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Conditional import: radar_core.browser_collector is only available when
# radar-core[browser] is installed (Playwright opt-in).
# ---------------------------------------------------------------------------
_BROWSER_COLLECTION_AVAILABLE = False
try:
    from radar_core.browser_collector import (
        collect_browser_sources as _core_collect,
    )

    _BROWSER_COLLECTION_AVAILABLE = True
except ImportError:
    _core_collect = None  # type: ignore[assignment]


def collect_browser_sources(
    sources: list[Source],
    category: str,
    *,
    timeout: int = 15_000,
    health_db_path: str | None = None,
) -> tuple[list[Article], list[str]]:
    """Collect articles from JavaScript-rendered sources via Playwright.

    Wraps :func:`radar_core.browser_collector.collect_browser_sources` and
    converts the returned ``radar_core.models.Article`` instances into local
    ``priceradar.models.Article`` instances for pipeline compatibility.

    Args:
        sources: Source objects with ``type`` in ``("javascript", "browser")``.
        category: Category name stamped onto every collected article.
        timeout: Default Playwright page-load timeout in milliseconds.
        health_db_path: Optional path to crawl-health DuckDB file.

    Returns:
        ``(articles, errors)`` -- local Article list and human-readable error
        strings.  On failure the articles list is empty and errors explains why.
    """
    if not sources:
        return [], []

    if not _BROWSER_COLLECTION_AVAILABLE or _core_collect is None:
        logger.warning(
            "browser_collection_unavailable",
            reason="radar_core.browser_collector not installed",
            source_count=len(sources),
            hint="pip install 'radar-core[browser]'",
        )
        return [], [
            f"Browser collection unavailable for {len(sources)} JS source(s). "
            "Install radar-core[browser]."
        ]

    try:
        source_dicts: list[dict[str, Any]] = [
            {"name": s.name, "type": s.type, "url": s.url} for s in sources
        ]
        core_articles, errors = _core_collect(
            sources=source_dicts,
            category=category,
            timeout=timeout,
            health_db_path=health_db_path,
        )
    except ImportError:
        # Playwright itself missing (radar-core installed but not [browser] extra)
        logger.warning(
            "playwright_not_installed",
            source_count=len(sources),
            hint="pip install 'radar-core[browser]'",
        )
        return [], [
            f"Playwright not installed for {len(sources)} JS source(s). "
            "Install radar-core[browser]."
        ]
    except Exception as exc:
        logger.error(
            "browser_collection_failed",
            error=str(exc),
            source_count=len(sources),
        )
        return [], [f"Browser collection failed: {exc}"]

    # Convert radar_core.models.Article -> local priceradar.models.Article
    local_articles: list[Article] = []
    for art in core_articles:
        local_articles.append(
            Article(
                title=art.title,
                link=art.link,
                summary=art.summary,
                published=art.published,
                source=art.source,
                category=art.category or category,
            )
        )

    if local_articles:
        logger.info(
            "browser_collection_complete",
            article_count=len(local_articles),
            error_count=len(errors),
        )

    return local_articles, errors
