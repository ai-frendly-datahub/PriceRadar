import hashlib
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from priceradar.collectors.base import BaseCollector, RawItem


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
        items: list[RawItem] = []
        seen_ids: set[str] = set()
        request_count = 0

        for endpoint in self.list_endpoints:
            path = endpoint["path"]
            list_type = endpoint["list_type"]
            max_pages = endpoint["max_pages"]

            for page in range(max_pages):
                page_url = self._build_more_url(path, page)

                if request_count > 0 and self.request_delay > 0:
                    time.sleep(self.request_delay)
                request_count += 1

                try:
                    html_content = self._fetch_html(page_url)
                except Exception as e:
                    print(f"[{self.source_id}] 목록 로드 실패 ({page_url}): {e}")
                    break

                if not html_content:
                    break

                soup = BeautifulSoup(html_content, "html.parser")
                product_elements = soup.select("li.post-li")
                if not product_elements:
                    break

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
            print(f"[{self.source_id}] HTML 가져오기 실패 ({url}): {e}")
            raise

    def _parse_product(self, product_elem: Tag, list_type: str = "latest") -> RawItem | None:
        detail_link_elem = product_elem.select_one("a.deal-detail-icon[href]")
        detail_href = str(detail_link_elem.get("href", "")).strip() if detail_link_elem else ""
        detail_url = urljoin(self.base_url, detail_href) if detail_href else None

        product_link_elem = product_elem.select_one("a.product-link[href]")
        if not product_link_elem:
            product_link_elem = product_elem.select_one("a.product-thumbnail-link[href]")

        product_href = str(product_link_elem.get("href", "")).strip() if product_link_elem else ""
        if not product_href:
            product_href = detail_href

        if not product_href:
            return None

        product_url = urljoin(self.base_url, product_href)

        title = product_link_elem.get_text(strip=True) if product_link_elem else ""
        if not title:
            title_elem = product_elem.select_one(".deal-title")
            title = title_elem.get_text(" ", strip=True) if title_elem else ""

        if not title:
            return None

        deal_id = self._extract_deal_id(detail_href) or self._extract_deal_id(product_href)
        product_id = (
            f"algumon_deal_{deal_id}" if deal_id else self._generate_product_id(product_url)
        )

        price_text = self._extract_text(product_elem.select_one(".deal-price-info .product-price"))
        if not price_text:
            price_text = self._extract_text(product_elem.select_one(".deal-price-text"))
        current_price = self._parse_price(price_text)

        title_text = self._extract_text(product_elem.select_one(".deal-title")) or title
        price_meta_text = self._extract_text(product_elem.select_one(".deal-price-meta-info"))
        discount_rate = self._parse_discount_rate(title_text, price_meta_text)

        image_url = None
        image_elem = product_elem.select_one(".product-img img")
        if image_elem and image_elem.get("src"):
            image_url = urljoin(self.base_url, str(image_elem.get("src")))

        shop_name = self._extract_text(product_elem.select_one(".label.shop a"))
        community = self._extract_text(product_elem.select_one(".label.site"))

        return RawItem(
            product_id=product_id,
            title=title,
            url=product_url,
            source=self.source_id,
            collected_at=datetime.now(),
            current_price=current_price,
            discount_rate=discount_rate,
            category=self.category,
            platform=self._infer_platform(shop_name, product_url),
            image_url=image_url,
            is_hotdeal=True,
            is_popular=list_type != "latest",
            raw_data={
                "deal_id": deal_id,
                "post_id": product_elem.get("data-post-id"),
                "list_type": list_type,
                "shop_name": shop_name,
                "community": community,
                "detail_url": detail_url,
                "price_text": price_text,
                "data_action_uri": product_elem.get("data-action-uri"),
            },
        )

    def _normalize_list_endpoints(self, raw_endpoints: Any) -> list[dict[str, Any]]:
        default_endpoints: list[dict[str, Any]] = [
            {"path": "/more", "list_type": "latest", "max_pages": 2},
            {"path": "/deal/rank/yesterday/more", "list_type": "yesterday_rank", "max_pages": 1},
            {"path": "/deal/toomuchlike/10/more", "list_type": "too_much_like", "max_pages": 1},
            {"path": "/deal/toomuchtalk/50/more", "list_type": "too_much_talk", "max_pages": 1},
        ]

        if not isinstance(raw_endpoints, list):
            return default_endpoints

        normalized: list[dict[str, Any]] = []
        for endpoint in raw_endpoints:
            if not isinstance(endpoint, dict):
                continue

            path = str(endpoint.get("path", "")).strip()
            if not path:
                continue
            if not path.startswith("/"):
                path = f"/{path}"

            try:
                max_pages = int(endpoint.get("max_pages", 1))
            except (TypeError, ValueError):
                max_pages = 1
            if max_pages < 1:
                max_pages = 1

            list_type = str(endpoint.get("list_type", "latest")).strip() or "latest"
            normalized.append({"path": path, "list_type": list_type, "max_pages": max_pages})

        return normalized or default_endpoints

    def _build_more_url(self, path: str, page: int) -> str:
        normalized_path = path.rstrip("/")
        return f"{self.base_url}{normalized_path}/{page}"

    def _extract_deal_id(self, url: str) -> str | None:
        patterns = [r"/m/deal/(\d+)", r"/l/d/(\d+)"]
        for pattern in patterns:
            matched = re.search(pattern, url)
            if matched:
                return matched.group(1)
        return None

    def _generate_product_id(self, url: str) -> str:
        hash_obj = hashlib.md5(url.encode())
        return f"{self.source_id}_{hash_obj.hexdigest()[:12]}"

    def _parse_price(self, price_text: str | None) -> int | None:
        if not price_text:
            return None

        matched = re.search(r"\d{1,3}(?:,\d{3})*|\d+", price_text)
        if not matched:
            return None

        return int(matched.group(0).replace(",", ""))

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
