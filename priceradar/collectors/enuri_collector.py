"""
Enuri Collector - 에누리 가격비교 사이트 크롤러

에누리(https://www.enuri.com)에서 최저가 상품 정보를 수집합니다.
"""

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from priceradar.collectors.base import BaseCollector, RawItem


class EnuriCollector(BaseCollector):
    """
    에누리 웹사이트에서 가격 정보를 수집하는 컬렉터

    데이터 소스:
    - 메인 페이지: 인기 상품 (jsonPopGoods)
    - 카테고리 페이지: 카테고리별 최저가
    """

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.base_url = "https://www.enuri.com"
        self.url = config.get("url", self.base_url)
        self.user_agent = config.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        self.timeout = config.get("timeout", 30)
        self.category = config.get("category", "all")
        self.category_code = config.get("category_code")  # gcate 파라미터
        self.best_goods_api_url = config.get(
            "best_goods_api_url",
            urljoin(self.base_url, "/m/ajax/main/getBestGoods_v4.jsp"),
        )
        self.best_goods_max = config.get("best_goods_max", 20)

    def collect(self) -> list[RawItem]:
        """에누리 페이지에서 상품 정보 수집"""
        try:
            items = self._collect_from_best_goods_api()
            if items:
                print(f"[{self.source_id}] {len(items)}개 상품 수집 완료")
                return items

            html_content = self._fetch_html(self.url)
            if not html_content:
                return []

            soup = BeautifulSoup(html_content, "html.parser")

            # JavaScript 데이터 추출
            items = self._parse_js_data(soup)

            print(f"[{self.source_id}] {len(items)}개 상품 수집 완료")
            return items

        except Exception as e:
            print(f"[{self.source_id}] 수집 실패: {e}")
            return []

    def _collect_from_best_goods_api(self) -> list[RawItem]:
        items: list[RawItem] = []
        seen_ids: set[str] = set()

        try:
            first_payload = self._fetch_best_goods(0)
        except Exception as e:
            print(f"[{self.source_id}] BestGoods API 호출 실패: {e}")
            return []

        payloads = [first_payload]
        for spm_code in self._extract_shop_codes(first_payload):
            if spm_code == 0:
                continue
            try:
                payloads.append(self._fetch_best_goods(spm_code))
            except Exception as e:
                print(f"[{self.source_id}] BestGoods API 탭 호출 실패 ({spm_code}): {e}")

        for payload in payloads:
            product_list = self._extract_best_goods_list(payload)
            if not self._is_best_goods_payload_success(payload, bool(product_list)):
                continue

            for product_data in product_list:
                if not isinstance(product_data, dict):
                    continue

                item = self._parse_product_from_best_goods(product_data)
                if not item:
                    continue
                if item.product_id in seen_ids:
                    continue
                if not self.validate_item(item):
                    continue

                seen_ids.add(item.product_id)
                items.append(item)

        return items

    def _is_best_goods_payload_success(
        self,
        payload: dict[str, Any],
        has_product_list: bool,
    ) -> bool:
        success_value = payload.get("success")

        if success_value is None:
            return has_product_list

        if isinstance(success_value, bool):
            return success_value

        if isinstance(success_value, str):
            normalized = success_value.strip().lower()
            return normalized in {"true", "y", "yes", "1", "ok", "success"}

        if isinstance(success_value, (int, float)):
            return success_value != 0

        return bool(success_value)

    def _extract_best_goods_list(self, payload: dict[str, Any]) -> list[Any]:
        candidates: list[Any] = [
            payload.get("list"),
            payload.get("goodsList"),
            payload.get("goods_list"),
        ]

        data_payload = payload.get("data")
        if isinstance(data_payload, dict):
            candidates.extend(
                [
                    data_payload.get("list"),
                    data_payload.get("goodsList"),
                    data_payload.get("goods_list"),
                ]
            )

        for candidate in candidates:
            if isinstance(candidate, list):
                return candidate

        return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _fetch_best_goods(self, spm_code: int) -> dict[str, Any]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": self.base_url,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        params = {
            "spm_cd": spm_code,
            "max": self.best_goods_max,
        }

        response = requests.get(
            self.best_goods_api_url,
            headers=headers,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("BestGoods API payload is not a dictionary")

        return payload

    def _extract_shop_codes(self, payload: dict[str, Any]) -> list[int]:
        tab_collections: list[Any] = [
            payload.get("tablist"),
            payload.get("tabClicklist"),
            payload.get("tab_click_list"),
        ]

        data_payload = payload.get("data")
        if isinstance(data_payload, dict):
            tab_collections.extend(
                [
                    data_payload.get("tablist"),
                    data_payload.get("tabClicklist"),
                    data_payload.get("tab_click_list"),
                ]
            )

        shop_codes: list[int] = []
        for tab_list in tab_collections:
            if not isinstance(tab_list, list):
                continue

            for tab_data in tab_list:
                if not isinstance(tab_data, dict):
                    continue

                raw_code = (
                    tab_data.get("shopCode")
                    or tab_data.get("shop_code")
                    or tab_data.get("spm_cd")
                    or tab_data.get("spmCd")
                )
                if raw_code is None:
                    continue

                try:
                    shop_code = int(str(raw_code))
                except (TypeError, ValueError):
                    continue

                if shop_code not in shop_codes:
                    shop_codes.append(shop_code)

        return shop_codes

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _fetch_html(self, url: str) -> str | None:
        """
        URL에서 HTML 가져오기 (재시도 로직 포함).

        최대 3회 재시도, 지수 백오프 대기 (2~10초).
        """
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

    def _parse_js_data(self, soup: BeautifulSoup) -> list[RawItem]:
        """JavaScript 데이터 객체에서 상품 정보 추출"""
        items: list[RawItem] = []

        # <script> 태그들을 탐색하여 jsonPopGoods 찾기
        script_tags = soup.find_all("script")

        for script in script_tags:
            script_content = script.string or script.get_text()
            if not script_content:
                continue

            # jsonPopGoods 변수 찾기
            if "jsonPopGoods" in script_content:
                products = self._extract_json_var(script_content, "jsonPopGoods")
                if products:
                    for product_data in products:
                        item = self._parse_product_from_json(product_data)
                        if item and self.validate_item(item):
                            items.append(item)

            # jsonPick도 확인 (기획전 상품)
            if "jsonPick" in script_content:
                pick_data = self._extract_json_var(script_content, "jsonPick")
                if pick_data and isinstance(pick_data, dict):
                    # pick_banner 배열 처리
                    banners = pick_data.get("pick_banner", [])
                    for banner in banners:
                        # 기획전 정보는 별도 처리 (필요 시)
                        pass

        return items

    def _parse_product_from_best_goods(self, product_data: dict[str, Any]) -> RawItem | None:
        try:
            title = str(product_data.get("gd_nm", "")).strip()
            if not title:
                return None

            product_url = str(product_data.get("pc_gd_url", "")).strip()
            if not product_url:
                product_number = product_data.get("pl_no")
                if not product_number:
                    return None
                product_url = (
                    f"{self.base_url}/move/Redirect.jsp"
                    f"?type=ex&cmd=move_{product_number}&pl_no={product_number}"
                )
            elif not product_url.startswith("http"):
                product_url = urljoin(self.base_url, product_url)

            current_price = self._parse_price(product_data.get("gd_prc"))
            if current_price is None or current_price <= 0:
                current_price = self._parse_price(product_data.get("spm_mber_prc"))
            if current_price is None or current_price <= 0:
                return None

            discount_rate = self._parse_discount_rate(
                product_data.get("pc_min_prc_decrs_rt")
                or product_data.get("mobl_min_prc_decrs_rt")
                or product_data.get("discount_rate")
            )
            if discount_rate is None:
                discount_rate = 0.0

            image_url = product_data.get("imgurl")
            if image_url and not str(image_url).startswith("http"):
                image_url = urljoin(self.base_url, str(image_url))

            shop_name = product_data.get("shop_nm")
            platform = self._infer_platform(shop_name, product_url)
            product_id = self._generate_product_id(product_url)

            return RawItem(
                product_id=product_id,
                title=title,
                url=product_url,
                source=self.source_id,
                collected_at=datetime.now(),
                current_price=current_price,
                discount_rate=discount_rate,
                category=self.category,
                platform=platform,
                image_url=str(image_url) if image_url else None,
                is_popular=True,
                raw_data={
                    "shop_name": shop_name,
                    "enuri_data": product_data,
                    "data_source": "best_goods_api",
                },
            )
        except Exception as e:
            print(f"[{self.source_id}] BestGoods 상품 파싱 실패: {e}")
            return None

    def _extract_json_var(self, script_content: str | None, var_name: str) -> Any:
        """JavaScript 변수에서 JSON 데이터 추출"""
        try:
            if not script_content:
                return None

            # 배열/객체 패턴 매칭 (탐욕적 매칭 사용)
            # jsonPopGoods = [...]; 형태
            patterns = [
                rf"(?:var\s+)?{var_name}\s*=\s*(\[.*?\])\s*;",  # 배열 (비탐욕적)
                rf"(?:var\s+)?{var_name}\s*=\s*(\{{.*?\}})\s*;",  # 객체 (비탐욕적)
                rf"(?:var\s+)?{var_name}\s*=\s*(\[.*?\])\s*(?:\n|$)",
                rf"(?:var\s+)?{var_name}\s*=\s*(\{{.*?\}})\s*(?:\n|$)",
            ]

            for pattern in patterns:
                # DOTALL 플래그로 여러 줄 매칭
                match = re.search(pattern, script_content, re.DOTALL)

                if match:
                    json_str = match.group(1)

                    # JSON 파싱 시도
                    try:
                        data = json.loads(json_str)
                        return data
                    except json.JSONDecodeError:
                        # 이 패턴으로 실패하면 다음 패턴 시도
                        continue

        except Exception as e:
            print(f"[{self.source_id}] 변수 추출 실패 ({var_name}): {e}")

        return None

    def _parse_price(self, value: Any) -> int | None:
        if value is None:
            return None

        raw_value = str(value).replace(",", "").strip()
        if not raw_value:
            return None

        matched = re.search(r"\d+", raw_value)
        if not matched:
            return None

        return int(matched.group(0))

    def _parse_discount_rate(self, value: Any) -> float | None:
        if value is None:
            return None

        raw_value = str(value).strip()
        if not raw_value:
            return None

        matched = re.search(r"\d+(?:\.\d+)?", raw_value)
        if not matched:
            return None

        numeric_value = float(matched.group(0))
        if numeric_value > 1.0:
            numeric_value = numeric_value / 100.0

        if numeric_value < 0.0 or numeric_value > 1.0:
            return None

        return numeric_value

    def _parse_product_from_json(self, product_data: dict[str, Any] | None) -> RawItem | None:
        """JSON 객체에서 RawItem 생성"""
        try:
            if not product_data:
                return None

            # 필수 필드 확인
            model_name = product_data.get("modelnm")
            if not model_name:
                return None

            # 가격 정보
            min_price_str = product_data.get("minprice", "0")
            min_price = int(min_price_str.replace(",", "")) if min_price_str else None

            # 할인율
            discount_rate_str = product_data.get("discount_rate", "0")
            discount_rate = None
            if discount_rate_str:
                # "25%" -> 0.25
                rate_match = re.search(r"(\d+)", discount_rate_str)
                if rate_match:
                    discount_rate = float(rate_match.group(1)) / 100.0

            # URL
            product_url = product_data.get("url", "")
            if not product_url.startswith("http"):
                product_url = urljoin(self.base_url, product_url)

            # 상품 ID 생성 (URL 기반)
            product_id = self._generate_product_id(product_url)

            # 이미지 URL
            image_url = product_data.get("strImgsrc")
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(self.base_url, image_url)

            # 판매처
            shop_name = product_data.get("shopnm")

            # 플랫폼 추론
            platform = self._infer_platform(shop_name, product_url)

            # RawItem 생성
            raw_item = RawItem(
                product_id=product_id,
                title=model_name,
                url=product_url,
                source=self.source_id,
                collected_at=datetime.now(),
                current_price=min_price,
                discount_rate=discount_rate,
                category=self.category,
                platform=platform,
                image_url=image_url,
                is_popular=True,  # jsonPopGoods는 인기 상품
                raw_data={
                    "shop_name": shop_name,
                    "enuri_data": product_data,
                },
            )

            return raw_item

        except Exception as e:
            print(f"[{self.source_id}] 상품 파싱 실패: {e}")
            return None

    def _generate_product_id(self, url: str) -> str:
        """URL 기반 상품 ID 생성"""
        hash_obj = hashlib.md5(url.encode())
        return f"{self.source_id}_{hash_obj.hexdigest()[:12]}"

    def _infer_platform(self, shop_name: str | None, url: str) -> str | None:
        """판매처명과 URL에서 플랫폼 추론"""
        if shop_name:
            shop_lower = shop_name.lower()
            if "쿠팡" in shop_name or "coupang" in shop_lower:
                return "coupang"
            elif "네이버" in shop_name or "naver" in shop_lower:
                return "naver"
            elif "g마켓" in shop_name or "gmarket" in shop_lower:
                return "gmarket"
            elif "11번가" in shop_name or "11st" in shop_lower:
                return "elevenst"
            elif "올리브영" in shop_name or "oliveyoung" in shop_lower:
                return "oliveyoung"

        # URL에서 추론
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        platform_mapping = {
            "coupang.com": "coupang",
            "shopping.naver.com": "naver",
            "gmarket.co.kr": "gmarket",
            "11st.co.kr": "elevenst",
            "oliveyoung.com": "oliveyoung",
        }

        for domain_key, platform in platform_mapping.items():
            if domain_key in domain:
                return platform

        return None


class EnuriCategoryCollector(EnuriCollector):
    """
    에누리 카테고리별 상품 수집

    URL 패턴: https://www.enuri.com/m/cpp.jsp?tab=enuri&gcate={category_code}
    """

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        # 카테고리 코드가 있으면 URL 생성
        category_code = config.get("category_code")
        if category_code:
            config["url"] = f"https://www.enuri.com/m/cpp.jsp?tab=enuri&gcate={category_code}"

        super().__init__(source_id, config)
