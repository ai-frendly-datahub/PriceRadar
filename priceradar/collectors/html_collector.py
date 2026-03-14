"""
HTML 수집기 - BeautifulSoup 기반 웹 페이지 크롤링
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import structlog
from bs4 import BeautifulSoup, Tag

from priceradar.collectors.base import BaseCollector, RawItem


logger = structlog.get_logger(__name__)


class HtmlCollector(BaseCollector):
    """HTML 페이지에서 가격 정보를 수집하는 컬렉터"""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.url = config.get("url", "")
        self.selectors = config.get("selectors", {})
        self.user_agent = config.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        self.timeout = config.get("timeout", 30)

    def collect(self) -> list[RawItem]:
        """URL에서 HTML을 가져와 파싱하여 RawItem 리스트 반환"""
        try:
            html_content = self._fetch_html(self.url)
            if not html_content:
                return []

            soup = BeautifulSoup(html_content, "html.parser")
            return self._parse_items(soup, self.url)

        except Exception as e:
            logger.error("collection_failed", source_id=self.source_id, error=str(e))
            return []

    def _fetch_html(self, url: str) -> str | None:
        """URL에서 HTML 콘텐츠를 가져옴"""
        headers = {"User-Agent": self.user_agent}

        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            return response.text
        except Exception as e:
            logger.error("html_fetch_failed", source_id=self.source_id, url=url, error=str(e))
            return None

    def _parse_items(self, soup: BeautifulSoup, base_url: str) -> list[RawItem]:
        """BeautifulSoup 객체에서 아이템들을 파싱"""
        items: list[RawItem] = []

        # 컨테이너 선택
        container_selector = self.selectors.get("container")
        if container_selector:
            container = soup.select_one(container_selector)
            if not container:
                logger.warning(
                    "container_not_found",
                    source_id=self.source_id,
                    selector=container_selector,
                )
                return []
        else:
            container = soup

        # 아이템 선택
        item_selector = self.selectors.get("item", ".product-item")
        item_elements = container.select(item_selector)

        if not item_elements:
            logger.warning("items_not_found", source_id=self.source_id, selector=item_selector)
            return []

        logger.info("items_found", source_id=self.source_id, count=len(item_elements))

        for elem in item_elements:
            try:
                item = self._parse_single_item(elem, base_url)
                if item and self.validate_item(item):
                    items.append(item)
            except Exception as e:
                logger.warning("item_parse_failed", source_id=self.source_id, error=str(e))
                continue

        return items

    def _parse_single_item(self, elem: Tag, base_url: str) -> RawItem | None:
        """단일 아이템 파싱"""
        # 제목
        title = self._extract_text(elem, self.selectors.get("title"))
        if not title:
            return None

        # URL
        link_selector = self.selectors.get("link", "a")
        link = self._extract_link(elem, link_selector, base_url)
        if not link:
            return None

        # 상품 ID 생성 (URL 기반 해시)
        product_id = self._generate_product_id(link)

        # 가격 정보
        current_price = self._extract_price(elem, self.selectors.get("price"))
        avg_price = self._extract_price(elem, self.selectors.get("avg_price"))
        list_price = self._extract_price(elem, self.selectors.get("list_price"))
        discount_rate = self._extract_discount_rate(elem, self.selectors.get("discount_rate"))

        # 이미지
        image_url = self._extract_image(elem, self.selectors.get("image"))

        # 카테고리
        category = self.config.get("category")

        # 플랫폼 추론 (URL에서)
        platform = self._infer_platform(link)

        # RawItem 생성
        raw_item = RawItem(
            product_id=product_id,
            title=title,
            url=link,
            source=self.source_id,
            collected_at=datetime.now(tz=UTC),
            current_price=current_price,
            avg_price=avg_price,
            list_price=list_price,
            discount_rate=discount_rate,
            category=category,
            platform=platform,
            image_url=image_url,
            raw_data={"html_snippet": str(elem)[:500]},
        )

        return raw_item

    def _extract_text(self, elem: Tag, selector: str | None) -> str | None:
        """텍스트 추출"""
        if not selector:
            return elem.get_text(strip=True)

        found = elem.select_one(selector)
        if found:
            return found.get_text(strip=True)
        return None

    def _extract_link(self, elem: Tag, selector: str, base_url: str) -> str | None:
        """링크 추출 및 절대 URL 변환"""
        found = elem.select_one(selector)
        if not found:
            return None

        href = found.get("href")
        if not isinstance(href, str) or not href:
            return None

        # 절대 URL로 변환
        return urljoin(base_url, href)

    def _extract_price(self, elem: Tag, selector: str | None) -> int | None:
        """가격 추출 (숫자만)"""
        if not selector:
            return None

        text = self._extract_text(elem, selector)
        if not text:
            return None

        # 숫자만 추출
        numbers = re.sub(r"[^\d]", "", text)
        if numbers:
            return int(numbers)
        return None

    def _extract_discount_rate(self, elem: Tag, selector: str | None) -> float | None:
        """할인율 추출 (0.0 ~ 1.0)"""
        if not selector:
            return None

        text = self._extract_text(elem, selector)
        if not text:
            return None

        # 숫자 추출 (예: "30%" -> 30)
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if match:
            rate = float(match.group(1))
            # 백분율을 0~1 사이로 변환
            if rate > 1:
                rate = rate / 100.0
            return rate
        return None

    def _extract_image(self, elem: Tag, selector: str | None) -> str | None:
        """이미지 URL 추출"""
        if not selector:
            return None

        found = elem.select_one(selector)
        if not found:
            return None

        # img 태그의 src 또는 data-src
        img_url = found.get("src") or found.get("data-src")
        if isinstance(img_url, str) and img_url:
            return urljoin(self.url, img_url)
        return None

    def _generate_product_id(self, url: str) -> str:
        """URL 기반으로 상품 ID 생성"""
        # URL 해시를 사용하여 고유 ID 생성
        hash_obj = hashlib.md5(url.encode())
        return f"{self.source_id}_{hash_obj.hexdigest()[:12]}"

    def _infer_platform(self, url: str) -> str | None:
        """URL에서 쇼핑몰 플랫폼 추론"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        platform_mapping = {
            "coupang.com": "coupang",
            "shopping.naver.com": "naver",
            "oliveyoung.com": "oliveyoung",
            "gmarket.co.kr": "gmarket",
            "11st.co.kr": "elevenst",
        }

        for domain_key, platform in platform_mapping.items():
            if domain_key in domain:
                return platform

        return None
