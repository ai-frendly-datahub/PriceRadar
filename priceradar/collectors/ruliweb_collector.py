from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from priceradar.collectors.base import BaseCollector, RawItem


class RuliwebCollector(BaseCollector):
    _POST_ID_PATTERN = re.compile(r"/read/(\d+)")
    _TRAILING_REPLY_PATTERN = re.compile(r"\s*\(\d+\)\s*$")
    _WON_SYMBOL_PATTERN = re.compile(r"[₩￦]\s*([0-9][0-9,]*)")
    _WON_SUFFIX_PATTERN = re.compile(r"([0-9][0-9,]*)\s*원")
    _MANWON_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*만\s*원")

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.base_url = "https://bbs.ruliweb.com"
        self.url = config.get("url", f"{self.base_url}/market/board/1020")
        self.user_agent = config.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        self.timeout = self._safe_int(config.get("timeout"), default=30)
        self.max_pages = max(1, self._safe_int(config.get("max_pages"), default=5))
        self.delay_between_requests = self._safe_float(
            config.get("delay_between_requests"), default=0.3
        )
        self.category = str(config.get("category", "market"))
        self.include_notice = bool(config.get("include_notice", False))

    def collect(self, page: int = 1, limit: int = 50) -> list[RawItem]:
        if limit <= 0:
            return []

        items: list[RawItem] = []
        seen_product_ids: set[str] = set()
        current_page = max(1, page)
        fetched_pages = 0

        while len(items) < limit and fetched_pages < self.max_pages:
            page_url = self._build_page_url(current_page)

            try:
                html_content = self._fetch_html(page_url)
            except Exception as exc:
                print(f"[{self.source_id}] 페이지 수집 실패 ({page_url}): {exc}")
                break

            soup = BeautifulSoup(html_content, "html.parser")
            post_rows = soup.select("tbody tr.table_body")
            if not post_rows:
                break

            for row in post_rows:
                item = self._parse_post(row)
                if not item:
                    continue
                if item.product_id in seen_product_ids:
                    continue
                if not self.validate_item(item):
                    continue

                seen_product_ids.add(item.product_id)
                items.append(item)

                if len(items) >= limit:
                    break

            fetched_pages += 1

            if len(items) >= limit:
                break
            if fetched_pages >= self.max_pages:
                break
            if not self._has_next_page(soup, current_page):
                break

            current_page += 1

            if self.delay_between_requests > 0:
                time.sleep(self.delay_between_requests)

        print(f"[{self.source_id}] {len(items)}개 게시글 수집 완료")
        return items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    def _fetch_html(self, url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        response = requests.get(url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def _build_page_url(self, page: int) -> str:
        parsed = urlparse(self.url)
        query = parse_qs(parsed.query, keep_blank_values=True)

        if page <= 1:
            query.pop("page", None)
        else:
            query["page"] = [str(page)]

        updated_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=updated_query))

    def _has_next_page(self, soup: BeautifulSoup, current_page: int) -> bool:
        target_page = current_page + 1

        for anchor in soup.select("a[href]"):
            raw_href = anchor.get("href")
            if isinstance(raw_href, list):
                if not raw_href:
                    continue
                href = str(raw_href[0])
            elif isinstance(raw_href, str):
                href = raw_href
            else:
                continue

            parsed = urlparse(urljoin(self.base_url, href))
            if not parsed.path.endswith("/market/board/1020"):
                continue

            query = parse_qs(parsed.query)
            page_values = query.get("page")
            if not page_values:
                continue

            try:
                page_value = int(page_values[0])
            except (TypeError, ValueError):
                continue

            if page_value == target_page:
                return True

        return False

    def _parse_post(self, row: Tag) -> RawItem | None:
        raw_row_classes = row.get("class")
        if isinstance(raw_row_classes, list):
            row_classes = {str(value) for value in raw_row_classes}
        else:
            row_classes = set()

        if "notice" in row_classes and not self.include_notice:
            return None

        subject_link = row.select_one("a.subject_link")
        if not subject_link:
            return None

        raw_href = subject_link.get("href")
        if isinstance(raw_href, list):
            if not raw_href:
                return None
            href = str(raw_href[0])
        elif isinstance(raw_href, str):
            href = raw_href
        else:
            return None

        post_url = urljoin(self.base_url, href)
        post_id = self._extract_post_id(post_url)
        if not post_id:
            return None

        title = self._normalize_title(subject_link.get_text(" ", strip=True))
        if not title:
            return None

        posted_at = self._extract_text(row, "td.time")
        board_section = self._extract_text(row, "td.divsn")
        current_price = self._extract_price_from_title(title)

        return RawItem(
            product_id=f"{self.source_id}_{post_id}",
            title=title,
            url=post_url,
            source=self.source_id,
            collected_at=datetime.now(tz=UTC),
            current_price=current_price,
            category=self.category,
            platform="ruliweb",
            raw_data={
                "post_id": post_id,
                "posted_at": posted_at,
                "board_section": board_section,
            },
        )

    def _extract_price_from_title(self, title: str) -> int | None:
        normalized_title = title.replace("\xa0", " ").strip()
        candidates: list[tuple[int, int]] = []

        for match in self._WON_SYMBOL_PATTERN.finditer(normalized_title):
            value = self._to_price_value(match.group(1))
            if value is not None:
                candidates.append((match.start(), value))

        for match in self._WON_SUFFIX_PATTERN.finditer(normalized_title):
            value = self._to_price_value(match.group(1))
            if value is not None:
                candidates.append((match.start(), value))

        for match in self._MANWON_PATTERN.finditer(normalized_title):
            try:
                value = int(float(match.group(1)) * 10000)
            except ValueError:
                continue
            if value >= 100:
                candidates.append((match.start(), value))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _extract_post_id(self, url: str) -> str | None:
        matched = self._POST_ID_PATTERN.search(url)
        if not matched:
            return None
        return matched.group(1)

    def _extract_text(self, row: Tag, selector: str) -> str | None:
        target = row.select_one(selector)
        if not target:
            return None

        text = target.get_text(" ", strip=True).replace("\xa0", " ").strip()
        if not text:
            return None
        return text

    def _normalize_title(self, title: str) -> str:
        normalized = title.replace("\xa0", " ").strip()
        normalized = self._TRAILING_REPLY_PATTERN.sub("", normalized).strip()
        return normalized

    def _to_price_value(self, raw_value: str) -> int | None:
        number_text = raw_value.replace(",", "").strip()
        if not number_text:
            return None

        try:
            value = int(number_text)
        except ValueError:
            return None

        if value < 100:
            return None

        return value

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, parsed)
