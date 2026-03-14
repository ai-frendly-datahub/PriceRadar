from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
import structlog
from bs4 import BeautifulSoup, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from priceradar.collectors.base import BaseCollector, RawItem


logger = structlog.get_logger(__name__)


class QuasarzoneCollector(BaseCollector):
    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.base_url = "https://quasarzone.com"
        self.board_path = "/bbs/qb_saleinfo"
        self.url = config.get("url", urljoin(self.base_url, self.board_path))
        self.user_agent = config.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        self.timeout = config.get("timeout", 30)
        self.request_delay = float(
            config.get("request_delay", config.get("delay_between_requests", 1.0))
        )
        self.max_pages = max(1, int(config.get("max_pages", 10)))

        self.platform_mapping = {
            "쿠팡": "coupang",
            "네이버": "naver",
            "지마켓": "gmarket",
            "g마켓": "gmarket",
            "11번가": "elevenst",
            "옥션": "auction",
            "롯데온": "lotteon",
            "하이마트": "himart",
            "알리": "aliexpress",
            "ssg": "ssg",
        }
        self.category_mapping = {
            "생활/식품": "food",
            "식품": "food",
            "가전/디지털": "electronics",
            "디지털": "electronics",
            "패션/의류": "fashion",
            "패션": "fashion",
            "뷰티": "beauty",
            "출산/유아": "baby",
            "유아": "baby",
            "반려": "pet",
            "스포츠": "sports",
        }

    def collect(self, page: int = 1, limit: int = 50) -> list[RawItem]:
        items: list[RawItem] = []
        seen_product_ids: set[str] = set()
        current_page = max(page, 1)
        pages_crawled = 0

        while len(items) < limit and pages_crawled < self.max_pages:
            pages_crawled += 1
            page_url = self._build_page_url(current_page)

            try:
                html_content = self._fetch_page(current_page)
            except Exception as e:
                logger.error(
                    "page_collect_failed",
                    source_id=self.source_id,
                    url=page_url,
                    error=str(e),
                )
                break

            page_items = self._parse_posts(html_content)
            if not page_items:
                break

            new_item_count = 0
            for item in page_items:
                if item.product_id in seen_product_ids:
                    continue
                if not self.validate_item(item):
                    continue

                seen_product_ids.add(item.product_id)
                items.append(item)
                new_item_count += 1

                if len(items) >= limit:
                    break

            if len(items) >= limit:
                break

            if new_item_count == 0:
                break

            current_page += 1
            if self.request_delay > 0:
                time.sleep(self.request_delay)

        return items[:limit]

    def _build_page_url(self, page: int) -> str:
        parsed = urlparse(self.url)

        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or urlparse(self.base_url).netloc
        path = parsed.path or self.board_path

        query = parse_qs(parsed.query, keep_blank_values=True)
        query["page"] = [str(page)]

        return urlunparse(
            (scheme, netloc, path, parsed.params, urlencode(query, doseq=True), parsed.fragment)
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _fetch_page(self, page: int) -> str:
        page_url = self._build_page_url(page)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": self.base_url,
        }

        response = requests.get(page_url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def _parse_posts(self, html_content: str) -> list[RawItem]:
        soup = BeautifulSoup(html_content, "html.parser")
        post_elements = soup.select("div.market-info-list-cont")

        items: list[RawItem] = []
        for post_elem in post_elements:
            try:
                item = self._parse_post(post_elem)
            except Exception as e:
                logger.warning("post_parse_failed", source_id=self.source_id, error=str(e))
                continue

            if item:
                items.append(item)

        return items

    def _parse_post(self, post_elem: Tag) -> RawItem | None:
        link_elem = post_elem.select_one("a.subject-link")
        if not link_elem:
            return None

        href_value = link_elem.get("href")
        if not isinstance(href_value, str) or not href_value.strip():
            return None
        href = href_value.strip()

        title_elem = link_elem.select_one("span.ellipsis-with-reply-cnt")
        title = (
            title_elem.get_text(" ", strip=True)
            if title_elem
            else link_elem.get_text(" ", strip=True)
        ).strip()
        if not title:
            return None

        post_url = urljoin(self.base_url, href)
        post_id = self._extract_post_id(post_url)
        if post_id:
            product_id = f"{self.source_id}_{post_id}"
        else:
            hash_obj = hashlib.md5(post_url.encode())
            product_id = f"{self.source_id}_{hash_obj.hexdigest()[:12]}"

        price_node = post_elem.select_one("span.text-orange")
        price_text = price_node.get_text(" ", strip=True) if price_node else None
        current_price = self._extract_price(price_text)
        if current_price is None:
            current_price = self._extract_price_from_title(title)
        if current_price is not None and current_price < 100:
            current_price = None

        discount_rate = self._extract_discount_rate(title)

        category_node = post_elem.select_one("span.category")
        raw_category = category_node.get_text(" ", strip=True) if category_node else None

        date_node = post_elem.select_one("span.date")
        posted_at = date_node.get_text(" ", strip=True) if date_node else None

        status_node = post_elem.select_one("span.label")
        status = status_node.get_text(" ", strip=True) if status_node else None

        author_node = post_elem.select_one("span.user-nick-wrap")
        author = author_node.get_text(" ", strip=True) if author_node else None

        views_node = post_elem.select_one("span.count")
        view_count_text = views_node.get_text(" ", strip=True) if views_node else None

        return RawItem(
            product_id=product_id,
            title=title,
            url=post_url,
            source=self.source_id,
            collected_at=datetime.now(tz=UTC),
            current_price=current_price,
            discount_rate=discount_rate,
            category=self._normalize_category(raw_category),
            platform=self._extract_platform_from_title(title),
            is_hotdeal=status == "진행중",
            raw_data={
                "board": "qb_saleinfo",
                "post_id": post_id,
                "price_text": price_text,
                "posted_at": posted_at,
                "status": status,
                "author": author,
                "view_count_text": view_count_text,
                "view_count": self._parse_view_count(view_count_text),
                "shipping": self._extract_shipping(post_elem),
                "raw_category": raw_category,
            },
        )

    def _extract_price(self, text: str | None) -> int | None:
        if not text:
            return None

        matched = re.search(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)", text)
        if not matched:
            return None

        return int(matched.group(1).replace(",", ""))

    def _extract_price_from_title(self, title: str) -> int | None:
        if not title:
            return None

        won_match = re.search(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{2,})\s*원", title)
        if won_match:
            return int(won_match.group(1).replace(",", ""))

        symbol_match = re.search(r"[₩￦]\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{2,})", title)
        if symbol_match:
            return int(symbol_match.group(1).replace(",", ""))

        man_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*만(?:원)?", title)
        if man_match:
            return int(float(man_match.group(1)) * 10000)

        return None

    def _extract_discount_rate(self, text: str) -> float | None:
        matched = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if not matched:
            return None

        rate = float(matched.group(1))
        if rate > 1.0:
            rate /= 100.0

        if rate < 0.0 or rate > 1.0:
            return None

        return rate

    def _extract_post_id(self, url: str) -> str | None:
        matched = re.search(r"/views/(\d+)", url)
        if not matched:
            return None
        return matched.group(1)

    def _extract_platform_from_title(self, title: str) -> str | None:
        matched = re.match(r"\[([^\]]+)\]", title.strip())
        if not matched:
            return None

        vendor = matched.group(1).strip().lower()
        for key, platform in self.platform_mapping.items():
            if key in vendor:
                return platform

        return None

    def _normalize_category(self, raw_category: str | None) -> str | None:
        if not raw_category:
            return None

        for key, normalized in self.category_mapping.items():
            if key in raw_category:
                return normalized

        return raw_category

    def _extract_shipping(self, post_elem: Tag) -> str | None:
        for span in post_elem.select("div.market-info-sub p span"):
            text = span.get_text(" ", strip=True)
            if text.startswith("배송비"):
                shipping = text.replace("배송비", "", 1).strip()
                return shipping or None

        return None

    def _parse_view_count(self, view_count_text: str | None) -> int | None:
        if not view_count_text:
            return None

        text = view_count_text.strip().lower().replace(",", "")
        if not text:
            return None

        if text.endswith("k"):
            try:
                return int(float(text[:-1]) * 1000)
            except ValueError:
                return None

        if text.isdigit():
            return int(text)

        try:
            return int(float(text))
        except ValueError:
            return None
