from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

import structlog

from priceradar.collectors.base import BaseCollector, RawItem


logger = structlog.get_logger(__name__)


class BrowserCollector(BaseCollector):
    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.url = str(config.get("url", "")).strip()
        self.category = str(config.get("category", "market"))

    def collect(self) -> list[RawItem]:
        if not self.url:
            return []

        browser_source = {
            "name": self.config.get("name", self.source_id),
            "type": "browser",
            "url": self.url,
            "config": {
                "timeout": int(self.config.get("timeout", 20_000)),
                "wait_for": self.config.get("wait_for"),
                "title_selector": self.config.get("title_selector"),
                "content_selector": self.config.get("content_selector"),
                "link_selector": self.config.get("link_selector"),
            },
        }

        try:
            browser_module = importlib.import_module("radar_core.browser_collector")
            collect_browser_sources = browser_module.collect_browser_sources
        except ImportError:
            logger.warning("playwright_unavailable", source_id=self.source_id)
            return []

        try:
            articles, errors = collect_browser_sources(
                [browser_source],
                category=self.category,
                timeout=int(self.config.get("timeout", 20_000)),
            )
        except Exception as exc:
            logger.error("browser_collection_failed", source_id=self.source_id, error=str(exc))
            return []

        for error in errors:
            logger.warning("browser_collection_error", source_id=self.source_id, error=error)

        items: list[RawItem] = []
        now = datetime.now(tz=UTC)
        for article in articles:
            if not article.link:
                continue

            product_id = f"{self.source_id}_{abs(hash(article.link))}"
            item = RawItem(
                product_id=product_id,
                title=article.title,
                url=article.link,
                source=self.source_id,
                collected_at=now,
                current_price=self._parse_price_from_text(article.title, article.summary),
                category=self.category,
                platform=self._infer_platform(article.link),
                is_hotdeal=True,
                raw_data={
                    "collection_method": "playwright",
                    "summary": article.summary,
                },
            )
            if self.validate_item(item):
                items.append(item)

        return items

    def _parse_price_from_text(self, title: str, summary: str) -> int | None:
        for text in (title, summary):
            value = self._parse_price_value(text)
            if value is not None:
                return value
        return None

    def _infer_platform(self, url: str) -> str | None:
        lower_url = url.lower()
        if "danawa" in lower_url:
            return "danawa"
        if "ppomppu" in lower_url:
            return "ppomppu"
        return None
