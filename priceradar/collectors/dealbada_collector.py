"""
Dealbada (딜바다) Collector - 핫딜 정보 수집기

딜바다에서 다양한 쇼핑몰의 핫딜 정보를 수집합니다.
- 상품명, URL, 가격 정보
- 할인율, 원가 정보
- 쇼핑몰 정보
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from priceradar.collectors.base import BaseCollector, RawItem


class DealbadaCollector(BaseCollector):
    """딜바다 핫딜 수집기"""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.base_url = "https://www.dealbada.com"
        self.board_url = config.get("url", f"{self.base_url}/hotdeal")
        self.user_agent = config.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        self.timeout = int(config.get("timeout", 30))
        self.request_delay = float(config.get("request_delay", 1.0))
        self.max_items = int(config.get("max_items", 100))
        self.max_pages = int(config.get("max_pages", 5))

    def collect(self) -> list[RawItem]:
        """딜바다에서 핫딜 정보 수집"""
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
                print(f"[{self.source_id}] 페이지 로드 실패 ({page_url}): {e}")
                break

            if not html_content:
                break

            soup = BeautifulSoup(html_content, "html.parser")
            deal_elements = soup.select("div.deal-item, li.deal-list-item")

            if not deal_elements:
                break

            for deal_elem in deal_elements:
                item = self._parse_deal(deal_elem)
                if not item:
                    continue
                if item.product_id in seen_ids:
                    continue
                if not self.validate_item(item):
                    continue

                seen_ids.add(item.product_id)
                items.append(item)

                if len(items) >= self.max_items:
                    print(f"[{self.source_id}] 최대 수집 수 도달: {self.max_items}")
                    return items

        print(f"[{self.source_id}] 총 {len(items)}개 상품 수집 완료")
        return items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _fetch_html(self, url: str) -> str | None:
        """HTTP 요청으로 HTML 가져오기"""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": self.board_url,
        }

        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except Exception as e:
            print(f"[{self.source_id}] HTML 가져오기 실패 ({url}): {e}")
            raise

    def _parse_deal(self, deal_elem: Tag) -> RawItem | None:
        """딜 요소에서 상품 정보 추출"""
        title_elem = deal_elem.select_one("a.deal-title, a.product-name")
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        if not title:
            return None

        deal_href = title_elem.get("href", "")
        if not deal_href:
            return None

        deal_url = urljoin(self.base_url, deal_href)

        deal_id_match = re.search(r"(\d+)", deal_href)
        deal_id = deal_id_match.group(1) if deal_id_match else None

        if not deal_id:
            deal_id = self._generate_product_id(deal_url)

        product_id = f"dealbada_{deal_id}"

        current_price = self._extract_price(deal_elem.select_one("span.current-price, span.price"))
        list_price = self._extract_price(
            deal_elem.select_one("span.list-price, span.original-price")
        )

        discount_rate = None
        if current_price and list_price and list_price > 0:
            discount_rate = (list_price - current_price) / list_price

        shop_elem = deal_elem.select_one("span.shop-name, a.shop")
        shop_name = shop_elem.get_text(strip=True) if shop_elem else "기타"

        category_elem = deal_elem.select_one("span.category, a.category")
        category = category_elem.get_text(strip=True) if category_elem else "기타"

        image_elem = deal_elem.select_one("img.product-image, img.deal-image")
        image_url = None
        if image_elem:
            image_url = image_elem.get("src") or image_elem.get("data-src")
            if image_url:
                image_url = urljoin(self.base_url, image_url)

        return RawItem(
            product_id=product_id,
            title=title,
            url=deal_url,
            source=self.source_id,
            collected_at=datetime.now(tz=UTC),
            current_price=current_price,
            list_price=list_price,
            discount_rate=discount_rate,
            category=category,
            platform=shop_name,
            image_url=image_url,
            raw_data={
                "deal_id": deal_id,
                "shop_name": shop_name,
                "category": category,
            },
        )

    def _extract_price(self, price_elem: Tag | None) -> int | None:
        """가격 요소에서 숫자 추출"""
        if not price_elem:
            return None

        price_text = price_elem.get_text(strip=True)
        price_match = re.search(r"(\d+(?:,\d{3})*)", price_text)

        if price_match:
            price_str = price_match.group(1).replace(",", "")
            try:
                return int(price_str)
            except ValueError:
                return None

        return None

    def _generate_product_id(self, url: str) -> str:
        """URL 기반 상품 ID 생성"""
        return hashlib.md5(url.encode()).hexdigest()[:12]
