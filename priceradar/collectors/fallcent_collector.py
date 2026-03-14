"""
Fallcent Collector - 폴센트 가격 추적 서비스 크롤러

폴센트(https://fallcent.com)에서 최저가 상품 정보를 수집합니다.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
import structlog
from bs4 import BeautifulSoup, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from priceradar.collectors.base import BaseCollector, RawItem


logger = structlog.get_logger(__name__)


class FallcentCollector(BaseCollector):
    """
    폴센트 웹사이트에서 가격 정보를 수집하는 컬렉터

    데이터 소스:
    - 메인 페이지: 지금 최저가
    - 카테고리별 급락 상품
    """

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.base_url = "https://fallcent.com"
        self.url = config.get("url", self.base_url)
        self.user_agent = config.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        self.timeout = config.get("timeout", 30)
        self.category = config.get("category", "all")

    def collect(self) -> list[RawItem]:
        """폴센트 페이지에서 상품 정보 수집"""
        try:
            html_content = self._fetch_html(self.url)
            if not html_content:
                return []

            soup = BeautifulSoup(html_content, "html.parser")
            return self._parse_products(soup)

        except Exception as e:
            logger.error("collection_failed", source_id=self.source_id, error=str(e))
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _fetch_html(self, url: str) -> str | None:
        """
        URL에서 HTML 가져오기 (재시도 로직 포함).

        최대 3회 재시도, 지수 백오프 대기 (2~10초).
        """
        headers = {"User-Agent": self.user_agent}

        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except Exception as e:
            logger.error("html_fetch_failed", source_id=self.source_id, url=url, error=str(e))
            raise

    def _parse_products(self, soup: BeautifulSoup) -> list[RawItem]:
        """상품 목록 파싱"""
        items: list[RawItem] = []

        # 폴센트는 카테고리별로 div 컨테이너를 사용 (id=카테고리명)
        # 카테고리 목록
        categories = [
            ("전체", "all"),
            ("식품", "food"),
            ("생활용품", "living"),
            ("가전/디지털", "electronics"),
            ("뷰티", "beauty"),
            ("출산/유아", "baby"),
            ("주방용품", "kitchen"),
            ("완구/취미", "toys"),
            ("패션의류", "fashion"),
            ("패션잡화", "accessories"),
            ("반려/애완용품", "pet"),
            ("가구/인테리어", "furniture"),
            ("스포츠/레저", "sports"),
            ("자동차용품", "automotive"),
            ("도서/음반", "books"),
            ("문구/오피스", "office"),
        ]

        # 카테고리별로 상품 수집
        for korean_name, english_name in categories:
            category_div = soup.find("div", id=korean_name)

            if not category_div:
                continue

            # 이 카테고리 div 내의 상품 링크 찾기
            product_links = category_div.find_all("a", href=re.compile(r"product_id=\d+"))

            for link in product_links:
                try:
                    item = self._parse_single_product(link, english_name)
                    if item and self.validate_item(item):
                        items.append(item)
                except Exception as e:
                    logger.warning("product_parse_failed", source_id=self.source_id, error=str(e))
                    continue

        logger.info("collection_complete", source_id=self.source_id, count=len(items))

        return items

    def _parse_single_product(self, link_elem: Tag, category: str = "all") -> RawItem | None:
        """단일 상품 정보 파싱"""
        # URL 파싱
        href = link_elem.get("href")
        if not isinstance(href, str) or not href:
            return None

        product_url = urljoin(self.base_url, href)
        parsed_url = urlparse(product_url)
        query_params = parse_qs(parsed_url.query)

        # product_id 추출
        product_id_list = query_params.get("product_id")
        if not product_id_list:
            return None

        coupang_product_id = product_id_list[0]
        product_id = f"fallcent_coupang_{coupang_product_id}"

        # 링크 내부의 모든 텍스트 추출
        all_text = link_elem.get_text(separator="\n", strip=True)
        text_lines = [line.strip() for line in all_text.split("\n") if line.strip()]

        # 상품명 추출 (보통 마지막 라인)
        title = None
        for line in reversed(text_lines):
            # 가격이나 할인율이 아닌 라인을 제목으로 간주
            if not re.search(r"^\d+%?$", line) and not re.search(r"^\d{1,3}(,\d{3})*원?$", line):
                if len(line) > 10:  # 충분히 긴 텍스트만 제목으로 간주
                    title = line
                    break

        if not title:
            return None

        # 가격 정보 추출
        current_price = None
        discount_rate = None

        for line in text_lines:
            # 가격 패턴 찾기 (예: "28,660원")
            price_match = re.search(r"(\d{1,3}(?:,\d{3})*)\s*원", line)
            if price_match and not current_price:
                price_str = price_match.group(1).replace(",", "")
                current_price = int(price_str)

            # 할인율 패턴 찾기 (예: "45%")
            discount_match = re.search(r"(\d+)\s*%", line)
            if discount_match and not discount_rate:
                discount_rate = float(discount_match.group(1)) / 100.0

        # 이미지 URL 추출
        img_elem = link_elem.find("img")
        image_url = None
        if img_elem:
            img_src = img_elem.get("src")
            if isinstance(img_src, str) and img_src:
                image_url = urljoin(self.base_url, img_src)

        # 로켓배송 여부 확인
        is_rocket = False
        rocket_img = link_elem.find("img", src=re.compile(r"rocket.*\.png"))
        if rocket_img:
            is_rocket = True

        # 최저가 여부 (폴센트 메인은 대부분 최저가)
        is_lowest_now = "최저가" in str(link_elem.parent) if link_elem.parent else False

        # RawItem 생성
        raw_item = RawItem(
            product_id=product_id,
            title=title,
            url=product_url,
            source=self.source_id,
            collected_at=datetime.now(tz=UTC),
            current_price=current_price,
            discount_rate=discount_rate,
            category=category,  # Use the detected category instead of self.category
            platform="coupang",
            image_url=image_url,
            is_lowest_now=is_lowest_now,
            raw_data={
                "is_rocket_delivery": is_rocket,
                "fallcent_url": product_url,
            },
        )

        return raw_item


class FallcentCategoryCollector(FallcentCollector):
    """
    폴센트 카테고리별 급락 상품 수집

    URL 패턴: https://fallcent.com/?category={category_name}
    """

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        # 카테고리 URL 생성
        category = config.get("category", "all")
        if category != "all":
            config["url"] = f"https://fallcent.com/?category={category}"

        super().__init__(source_id, config)

        # 급락 상품이므로 is_hotdeal 플래그 추가
        self.is_category_drop = True

    def _parse_single_product(self, link_elem: Tag, category: str = "all") -> RawItem | None:
        """카테고리별 급락 상품 파싱 (부모 메서드 확장)"""
        item = super()._parse_single_product(link_elem, category)

        if item:
            # 급락 상품 플래그 설정
            item.is_hotdeal = self.is_category_drop
            item.raw_data["list_type"] = "category_drop"

        return item
