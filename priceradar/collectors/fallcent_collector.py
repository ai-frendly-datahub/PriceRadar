"""
Fallcent Collector - 폴센트 가격 추적 서비스 크롤러

폴센트(https://fallcent.com)에서 최저가 상품 정보를 수집합니다.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

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
        """상품 목록 파싱

        2026-05 기준 폴센트 홈은 캐러셀형 추천 상품을 렌더링한다.
        각 상품은 `<a href="/product/<HASH>/?from=home">` 앵커이며 내부에
        `<p class="line-clamp-2">` (상품명), `<span>가격원</span>`,
        `<img alt="...">` (썸네일) 을 포함한다. (구) `div[id=<category>]`
        구조는 더 이상 존재하지 않는다.
        """
        items: list[RawItem] = []

        product_links = soup.find_all(
            "a", href=re.compile(r"^/product/[A-Za-z0-9_-]{6,}/")
        )
        if not product_links:
            logger.warning(
                "schema_invalid_skip_source",
                source_id=self.source_id,
                missing_elements=[
                    {
                        "element": "product_anchor",
                        "selector": 'a[href^="/product/"]',
                    }
                ],
            )
            return []

        seen_product_ids: set[str] = set()
        for link in product_links:
            try:
                item = self._parse_single_product(link, self.category)
            except Exception as e:
                logger.warning("product_parse_failed", source_id=self.source_id, error=str(e))
                continue

            if not item:
                continue
            if item.product_id in seen_product_ids:
                continue
            if not self.validate_item(item):
                continue

            seen_product_ids.add(item.product_id)
            items.append(item)

        logger.info("collection_complete", source_id=self.source_id, count=len(items))

        return items

    def _parse_single_product(self, link_elem: Tag, category: str = "all") -> RawItem | None:
        """단일 상품 정보 파싱

        새 폴센트 스키마 가정:
          <a href="/product/<HASH>/?from=...">
            <img alt="<상품명>" src="...">
            <p ... line-clamp-2 ...>상품명</p>
            <span ...>가격원</span>   (예: "3,160원")
          </a>
        """
        href = link_elem.get("href")
        if not isinstance(href, str) or not href:
            return None

        product_url = urljoin(self.base_url, href)
        parsed_url = urlparse(product_url)

        # /product/<HASH>/ 에서 HASH 추출 → product_id
        path_match = re.match(r"^/product/([A-Za-z0-9_-]+)/?", parsed_url.path)
        if not path_match:
            return None

        fallcent_hash = path_match.group(1)
        if fallcent_hash in {"recommend", "search"}:
            return None
        product_id = f"fallcent_{fallcent_hash}"

        # 제목 추출: <p class="...line-clamp-2..."> 우선, 그 다음 img[alt]
        title: str | None = None
        title_elem = link_elem.find("p", class_=re.compile(r"line-clamp"))
        if title_elem:
            title = title_elem.get_text(" ", strip=True) or None

        img_elem = link_elem.find("img")
        image_url: str | None = None
        if img_elem:
            img_src = img_elem.get("src")
            if isinstance(img_src, str) and img_src:
                image_url = urljoin(self.base_url, img_src)
            if not title:
                alt_text = img_elem.get("alt")
                if isinstance(alt_text, str) and alt_text.strip():
                    title = alt_text.strip()

        if not title:
            return None

        # 가격 추출: 앵커 안의 모든 텍스트에서 ", "<숫자>,<숫자>원" 패턴 첫 매치.
        # NOTE: BaseCollector._parse_price_value 는 콤마를 공백으로 치환 후 첫
        # 숫자 토큰만 잡으므로 "3,790" 같은 값을 그대로 넘기면 결과가 잘려 나온다.
        # 그래서 매치 결과의 콤마를 직접 제거한 뒤 호출한다.
        anchor_text = link_elem.get_text(" ", strip=True)
        current_price: int | None = None
        price_match = re.search(r"(\d{1,3}(?:,\d{3})+|\d{3,})\s*원", anchor_text)
        if price_match:
            current_price = self._parse_price_value(price_match.group(1).replace(",", ""))

        # 할인율: 앵커 내부 또는 부모 컨테이너 텍스트에서 N% 패턴
        discount_rate: float | None = None
        scope_text = anchor_text
        parent = link_elem.parent
        if parent:
            scope_text = parent.get_text(" ", strip=True)
        discount_match = re.search(r"(\d{1,2})\s*%", scope_text)
        if discount_match:
            try:
                rate = float(discount_match.group(1)) / 100.0
                if 0.0 < rate <= 1.0:
                    discount_rate = rate
            except ValueError:
                discount_rate = None

        # 로켓 배송 여부 (badge img/svg src or text)
        is_rocket = False
        for tag in link_elem.find_all("img"):
            src = tag.get("src") or ""
            if isinstance(src, str) and re.search(r"rocket|herb", src):
                is_rocket = True
                break

        # 최저가 표기 (앵커 또는 인접 형제 텍스트)
        is_lowest_now = False
        if "최저가" in anchor_text:
            is_lowest_now = True
        elif parent and "최저가" in parent.get_text(" ", strip=True):
            is_lowest_now = True

        return RawItem(
            product_id=product_id,
            title=title,
            url=product_url,
            source=self.source_id,
            collected_at=datetime.now(tz=UTC),
            current_price=current_price,
            discount_rate=discount_rate,
            category=category,
            platform="coupang",
            image_url=image_url,
            is_lowest_now=is_lowest_now,
            raw_data={
                "is_rocket_delivery": is_rocket,
                "fallcent_url": product_url,
                "fallcent_hash": fallcent_hash,
            },
        )


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
