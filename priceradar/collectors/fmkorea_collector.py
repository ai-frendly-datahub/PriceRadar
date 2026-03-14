"""
FMKorea (펨코) Collector - 핫딜 게시판 수집기

펨코 핫딜 게시판에서 상품 정보를 수집합니다.
- 게시물 제목, URL, 가격 정보
- 추천 수, 댓글 수 등 인기도 지표
- 카테고리 분류
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import requests
import structlog
from bs4 import BeautifulSoup, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from priceradar.collectors.base import BaseCollector, RawItem


logger = structlog.get_logger(__name__)


class FmkoreaCollector(BaseCollector):
    """펨코 핫딜 게시판 수집기"""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.base_url = "https://www.fmkorea.com"
        self.board_url = config.get("url", f"{self.base_url}/hotdeal")
        self.user_agent = config.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        self.timeout = int(config.get("timeout", 30))
        self.request_delay = float(config.get("request_delay", 3.0))
        self.max_items = int(config.get("max_items", 200))
        self.max_pages = int(config.get("max_pages", 10))

        # Initialize session with persistent cookies and headers
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Referer": self.base_url,
            }
        )

    def collect(self) -> list[RawItem]:
        """펨코 핫딜 게시판에서 상품 정보 수집"""
        items: list[RawItem] = []
        seen_ids: set[str] = set()
        request_count = 0

        for page in range(1, self.max_pages + 1):
            page_url = f"{self.board_url}?page={page}"

            if request_count > 0 and self.request_delay > 0:
                time.sleep(self.request_delay)
            request_count += 1

            try:
                html_content = self._fetch_html(page_url)
            except Exception as e:
                logger.error(
                    "page_load_failed", source_id=self.source_id, url=page_url, error=str(e)
                )
                break

            if not html_content:
                break

            soup = BeautifulSoup(html_content, "html.parser")
            post_elements = soup.select("div.post-item, tr.list-item")

            if not post_elements:
                break

            for post_elem in post_elements:
                item = self._parse_post(post_elem)
                if not item:
                    continue
                if item.product_id in seen_ids:
                    continue
                if not self.validate_item(item):
                    continue

                seen_ids.add(item.product_id)
                items.append(item)

                if len(items) >= self.max_items:
                    logger.info(
                        "max_items_reached",
                        source_id=self.source_id,
                        max_items=self.max_items,
                    )
                    return items

        logger.info("collection_complete", source_id=self.source_id, count=len(items))
        return items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _fetch_html(self, url: str) -> str | None:
        """HTTP 요청으로 HTML 가져오기"""
        try:
            response = self.session.get(url, timeout=self.timeout)

            if response.status_code == 430:
                time.sleep(5)
                raise requests.exceptions.HTTPError(f"Rate limited (430): {url}")

            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except Exception as e:
            logger.error("html_fetch_failed", source_id=self.source_id, url=url, error=str(e))
            raise

    def _parse_post(self, post_elem: Tag) -> RawItem | None:
        """게시물 요소에서 상품 정보 추출"""
        title_elem = post_elem.select_one("a.post-title, a.subject")
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        if not title:
            return None

        post_href = title_elem.get("href", "")
        if not post_href:
            return None

        post_url = urljoin(self.base_url, post_href)

        post_id_match = re.search(r"(\d+)", post_href)
        post_id = post_id_match.group(1) if post_id_match else None

        if not post_id:
            post_id = self._generate_product_id(post_url)

        product_id = f"fmkorea_{post_id}"

        price = self._extract_price_from_title(title)

        category_elem = post_elem.select_one("span.category, td.category")
        category = category_elem.get_text(strip=True) if category_elem else "기타"

        recommend_elem = post_elem.select_one("span.recommend, td.recommend")
        recommend_count = 0
        if recommend_elem:
            recommend_text = recommend_elem.get_text(strip=True)
            recommend_match = re.search(r"(\d+)", recommend_text)
            if recommend_match:
                recommend_count = int(recommend_match.group(1))

        comment_elem = post_elem.select_one("span.comment, td.comment")
        comment_count = 0
        if comment_elem:
            comment_text = comment_elem.get_text(strip=True)
            comment_match = re.search(r"(\d+)", comment_text)
            if comment_match:
                comment_count = int(comment_match.group(1))

        is_popular = recommend_count > 50 or comment_count > 20

        return RawItem(
            product_id=product_id,
            title=title,
            url=post_url,
            source=self.source_id,
            collected_at=datetime.now(tz=UTC),
            current_price=price,
            category=category,
            platform="fmkorea",
            is_popular=is_popular,
            raw_data={
                "post_id": post_id,
                "recommend_count": recommend_count,
                "comment_count": comment_count,
                "category": category,
            },
        )

    def _extract_price_from_title(self, title: str) -> int | None:
        """제목에서 가격 정보 추출"""
        price_patterns = [
            r"(\d+(?:,\d{3})*)\s*원",
            r"(\d+(?:,\d{3})*)\s*\/",
            r"₩\s*(\d+(?:,\d{3})*)",
        ]

        for pattern in price_patterns:
            match = re.search(pattern, title)
            if match:
                price_str = match.group(1).replace(",", "")
                try:
                    return int(price_str)
                except ValueError:
                    continue

        return None

    def _generate_product_id(self, url: str) -> str:
        """URL 기반 상품 ID 생성"""
        return hashlib.md5(url.encode()).hexdigest()[:12]
