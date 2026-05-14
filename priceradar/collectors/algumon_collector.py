from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import structlog
from bs4 import BeautifulSoup, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from priceradar.collectors.base import BaseCollector, RawItem


logger = structlog.get_logger(__name__)


class AlgumonCollector(BaseCollector):
    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.base_url = "https://www.algumon.com"
        self.url = config.get("url", f"{self.base_url}/")
        self.user_agent = config.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        self.timeout = int(config.get("timeout", 30))
        self.category = config.get("category", "electronics")
        self.request_delay = float(config.get("request_delay", 1.0))
        self.max_items = int(config.get("max_items", 120))
        self.list_endpoints = self._normalize_list_endpoints(config.get("list_endpoints"))

    def collect(self) -> list[RawItem]:
        """알구몬 핫딜 SSR 페이지에서 카드 정보를 수집한다.

        2026-05 기준 알구몬은 SvelteKit SPA 로 재설계되어 기존 `/more/<page>`
        엔드포인트들은 모두 404 를 반환한다. 현재 SSR 가용 경로는 `/n/deal`
        한 개이며 한 요청에 9개 카드가 노출된다. `?cursor=<deal_id>` 쿼리로
        해당 deal_id 직전 9개를 받아오는 방식으로 페이지네이션할 수 있다.

        max_pages 만큼 cursor 를 따라 내려가며 max_items 까지 수집한다.
        max_items 이전에 카드가 더 안 나오면 멈춘다.
        """
        items: list[RawItem] = []
        seen_ids: set[str] = set()
        request_count = 0

        for endpoint in self.list_endpoints:
            path = endpoint["path"]
            list_type = endpoint["list_type"]
            max_pages = int(endpoint.get("max_pages", 1))
            cursor: str | None = None

            for _page_idx in range(max(1, max_pages)):
                page_url = urljoin(self.base_url, path)
                if cursor:
                    sep = "&" if "?" in page_url else "?"
                    page_url = f"{page_url}{sep}cursor={cursor}"

                if request_count > 0 and self.request_delay > 0:
                    time.sleep(self.request_delay)
                request_count += 1

                try:
                    html_content = self._fetch_html(page_url)
                except Exception as e:
                    logger.error(
                        "page_load_failed",
                        source_id=self.source_id,
                        url=page_url,
                        error=str(e),
                    )
                    break

                if not html_content:
                    break

                soup = BeautifulSoup(html_content, "html.parser")
                if not self._validate_html_schema(
                    soup,
                    {
                        "deal_card": "div.deal-feed-card",
                        "deal_card_title": "div.deal-feed-card h3 a",
                    },
                    context=page_url,
                ):
                    logger.warning(
                        "schema_invalid_skip_source",
                        source_id=self.source_id,
                        url=page_url,
                    )
                    break

                product_elements = soup.select("div.deal-feed-card")
                if not product_elements:
                    break

                new_in_page = 0
                lowest_deal_id: int | None = None
                for product_elem in product_elements:
                    item = self._parse_product(product_elem, list_type=list_type)
                    if not item:
                        continue
                    if item.product_id in seen_ids:
                        continue
                    if not self.validate_item(item):
                        continue

                    seen_ids.add(item.product_id)
                    items.append(item)
                    new_in_page += 1

                    deal_id_raw = item.raw_data.get("deal_id")
                    if deal_id_raw and str(deal_id_raw).isdigit():
                        deal_int = int(deal_id_raw)
                        if lowest_deal_id is None or deal_int < lowest_deal_id:
                            lowest_deal_id = deal_int

                    if len(items) >= self.max_items:
                        logger.info(
                            "max_items_reached",
                            source_id=self.source_id,
                            max_items=self.max_items,
                        )
                        return items

                if new_in_page == 0 or lowest_deal_id is None:
                    break
                cursor = str(lowest_deal_id)

        logger.info("collection_complete", source_id=self.source_id, count=len(items))
        return items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _fetch_html(self, url: str) -> str | None:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except Exception as e:
            logger.error("html_fetch_failed", source_id=self.source_id, url=url, error=str(e))
            raise

    def _parse_product(self, product_elem: Tag, list_type: str = "latest") -> RawItem | None:
        """알구몬 deal-feed-card 한 장을 RawItem 으로 변환.

        새 스키마 가정:
          <div class="deal-feed-card" id="deal-<DEAL_ID>">
            <h3 ...><a href="https://www.algumon.com/l/d/<DEAL_ID>?...">제목</a></h3>
            <img src="..." alt="제목">
            <p class="deal-price-text">8,910원 (12 x 742원)</p>
            <a class="badge ..." href="/n/deal?keyword=쿠팡">쿠팡</a>
            ...
        """
        # 외부 상품 링크 (h3 a) 와 알구몬 내부 상세 링크 (/n/deal/<id>) 모두 확인
        title_anchor = product_elem.select_one("h3 a[href]")
        detail_anchor = product_elem.select_one(f'a[href^="{self.base_url}/l/d/"]')
        if title_anchor is None:
            title_anchor = detail_anchor

        if title_anchor is None:
            return None

        title_href = str(title_anchor.get("href", "")).strip()
        if not title_href:
            return None

        # deal_id 추출: card id 우선 (예: id="deal-976827"), 그 다음 href 패턴
        card_id = str(product_elem.get("id", "")).strip()
        deal_id: str | None = None
        card_match = re.match(r"^deal-(\d+)$", card_id)
        if card_match:
            deal_id = card_match.group(1)
        if not deal_id:
            deal_id = self._extract_deal_id(title_href)

        product_url = title_href
        if not product_url.startswith("http"):
            product_url = urljoin(self.base_url, product_url)

        product_id = (
            f"algumon_deal_{deal_id}" if deal_id else self._generate_product_id(product_url)
        )

        title = title_anchor.get_text(" ", strip=True)
        if not title:
            return None

        # 가격: .deal-price-text 우선. 텍스트는 "8,910원 (12 x 742원)" 같은
        # 복합 형식이라 BaseCollector._parse_price_value 가 콤마를 공백으로
        # 바꾼 뒤 첫 토큰만 잡으면 "8" 처럼 잘려 나온다. 천단위 콤마를 포함한
        # 첫 가격 토큰을 직접 매칭해 콤마 제거 후 helper 에 넘긴다.
        price_text = self._extract_text(product_elem.select_one(".deal-price-text"))
        current_price: int | None = None
        if price_text:
            primary_match = re.search(r"(\d{1,3}(?:,\d{3})+|\d{3,})\s*원", price_text)
            if primary_match:
                current_price = self._parse_price(primary_match.group(1).replace(",", ""))
        if current_price is None:
            current_price = self._parse_price(price_text)

        discount_rate = self._parse_discount_rate(title, price_text)

        image_url = None
        image_elem = product_elem.find("img")
        if image_elem is not None:
            img_src = image_elem.get("src")
            if isinstance(img_src, str) and img_src:
                image_url = urljoin(self.base_url, img_src)

        # 쇼핑몰 라벨: 첫 번째 badge 링크 (keyword= 쿼리 포함)
        shop_name: str | None = None
        for badge in product_elem.select(
            'a.badge[href*="keyword="], span.badge'
        ):
            text = badge.get_text(" ", strip=True)
            if text:
                shop_name = text
                break

        # detail_url: 알구몬 내부 상세 페이지 (있을 때만)
        detail_url = None
        internal_anchor = product_elem.select_one('a[href^="/n/deal/"]')
        if internal_anchor is not None:
            internal_href = str(internal_anchor.get("href", "")).strip()
            if internal_href:
                detail_url = urljoin(self.base_url, internal_href)

        return RawItem(
            product_id=product_id,
            title=title,
            url=product_url,
            source=self.source_id,
            collected_at=datetime.now(tz=UTC),
            current_price=current_price,
            discount_rate=discount_rate,
            category=self.category,
            platform=self._infer_platform(shop_name, product_url),
            image_url=image_url,
            is_hotdeal=True,
            is_popular=list_type != "latest",
            raw_data={
                "deal_id": deal_id,
                "list_type": list_type,
                "shop_name": shop_name,
                "detail_url": detail_url,
                "price_text": price_text,
                "card_id": card_id,
            },
        )

    def _normalize_list_endpoints(self, raw_endpoints: Any) -> list[dict[str, Any]]:
        """알구몬 SvelteKit SPA 의 SSR 진입점만 허용.

        과거 `/more`, `/deal/rank/yesterday/more`, `/deal/toomuchlike/...`
        등은 2026-05 현재 모두 404 다. 현재 살아 있는 페이지는 `/n/deal`
        한 개이며 `?cursor=<deal_id>` 로 페이지를 거슬러 올라간다.
        """
        default_endpoints: list[dict[str, Any]] = [
            {"path": "/n/deal", "list_type": "latest", "max_pages": 4},
        ]

        if not isinstance(raw_endpoints, list):
            return default_endpoints

        # 죽은 경로는 무시하고 살아 있는 SSR 경로만 통과시킨다.
        live_paths = {"/n/deal", "/n/deal/"}
        normalized: list[dict[str, Any]] = []
        for endpoint in raw_endpoints:
            if not isinstance(endpoint, dict):
                continue

            path = str(endpoint.get("path", "")).strip()
            if not path:
                continue
            if not path.startswith("/"):
                path = f"/{path}"

            if path not in live_paths:
                # config 에 옛 엔드포인트가 남아 있어도 무시 (회귀 방지)
                continue

            try:
                max_pages = int(endpoint.get("max_pages", 1))
            except (TypeError, ValueError):
                max_pages = 1
            if max_pages < 1:
                max_pages = 1

            list_type = str(endpoint.get("list_type", "latest")).strip() or "latest"
            normalized.append({"path": path, "list_type": list_type, "max_pages": max_pages})

        return normalized or default_endpoints

    def _extract_deal_id(self, url: str) -> str | None:
        # 알구몬 외부 상품 링크: https://www.algumon.com/l/d/<DEAL_ID>?...
        # 내부 상세 링크: /n/deal/<DEAL_ID>
        # 구) /m/deal/<DEAL_ID> 도 유지
        patterns = [r"/m/deal/(\d+)", r"/l/d/(\d+)", r"/n/deal/(\d+)"]
        for pattern in patterns:
            matched = re.search(pattern, url)
            if matched:
                return matched.group(1)
        return None

    def _generate_product_id(self, url: str) -> str:
        hash_obj = hashlib.md5(url.encode())
        return f"{self.source_id}_{hash_obj.hexdigest()[:12]}"

    def _parse_price(self, price_text: str | None) -> int | None:
        return self._parse_price_value(price_text)

    def _parse_discount_rate(self, *texts: str | None) -> float | None:
        discount_keywords = ["할인", "off", "세일", "쿠폰", "최대", "인하"]

        for text in texts:
            if not text or "%" not in text:
                continue

            lowered = text.lower()
            if not any(keyword in lowered for keyword in discount_keywords):
                continue

            matched = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if not matched:
                continue

            discount_rate = float(matched.group(1))
            if discount_rate > 1.0:
                discount_rate = discount_rate / 100.0

            if 0.0 <= discount_rate <= 1.0:
                return discount_rate

        return None

    def _infer_platform(self, shop_name: str | None, product_url: str) -> str | None:
        if shop_name:
            shop_lower = shop_name.lower().replace(" ", "")
            if "쿠팡" in shop_name or "coupang" in shop_lower:
                return "coupang"
            if "네이버" in shop_name or "naver" in shop_lower:
                return "naver"
            if "11번가" in shop_name or "11st" in shop_lower:
                return "elevenst"
            if "g마켓" in shop_name or "gmarket" in shop_lower:
                return "gmarket"
            if "옥션" in shop_name or "auction" in shop_lower:
                return "auction"

        parsed = urlparse(product_url)
        domain = parsed.netloc.lower()

        platform_mapping = {
            "coupang.com": "coupang",
            "shopping.naver.com": "naver",
            "11st.co.kr": "elevenst",
            "gmarket.co.kr": "gmarket",
            "auction.co.kr": "auction",
        }

        for domain_key, platform in platform_mapping.items():
            if domain_key in domain:
                return platform

        return None

    def _extract_text(self, elem: Tag | None) -> str | None:
        if not elem:
            return None

        text = elem.get_text(" ", strip=True)
        return text if text else None
