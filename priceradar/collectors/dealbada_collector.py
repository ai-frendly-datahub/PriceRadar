"""
Dealbada (딜바다) Collector - 핫딜 정보 수집기

딜바다 gnuboard5 BBS (`/bbs/board.php?bo_table=deal_domestic`)에서 국내 핫딜
정보를 수집합니다.
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
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
import structlog
from bs4 import BeautifulSoup, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from priceradar.collectors.base import BaseCollector, RawItem


logger = structlog.get_logger(__name__)


class DealbadaCollector(BaseCollector):
    """딜바다 핫딜 수집기 (gnuboard5 기반)"""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self.base_url = "https://www.dealbada.com"
        self.board_url = config.get(
            "url",
            f"{self.base_url}/bbs/board.php?bo_table=deal_domestic",
        )
        self.user_agent = config.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        self.timeout = int(config.get("timeout", 30))
        self.request_delay = float(config.get("request_delay", 1.0))
        self.max_items = int(config.get("max_items", 100))
        self.max_pages = int(config.get("max_pages", 5))

    def _build_page_url(self, page: int) -> str:
        """gnuboard 기반 게시판 URL에 page 파라미터를 안전하게 부착."""
        parsed = urlparse(self.board_url)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        # 기존 page 파라미터는 제거 후 새 값으로 대체
        query_pairs = [(k, v) for (k, v) in query_pairs if k != "page"]
        query_pairs.append(("page", str(page)))
        new_query = urlencode(query_pairs)
        return urlunparse(parsed._replace(query=new_query))

    def collect(self) -> list[RawItem]:
        """딜바다 핫딜 게시판에서 상품 정보 수집"""
        items: list[RawItem] = []
        seen_ids: set[str] = set()
        request_count = 0

        # gnuboard5 표준 row 패턴 — 본문 행(`<tr class="">`)과 일부 강조 행을
        # 모두 잡고, 공지(`tr.bo_notice`)는 별도로 걸러낸다.
        row_selector = (
            "table tbody tr:has(td.td_subject), "
            "table tr:has(td.td_subject)"
        )
        title_selector = "td.td_subject a[href*='wr_id=']"

        for page in range(1, self.max_pages + 1):
            page_url = self._build_page_url(page)

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
            if not self._validate_html_schema(
                soup,
                {
                    "deal_row": row_selector,
                    "title_link": title_selector,
                },
                context=page_url,
            ):
                logger.warning("schema_invalid_skip_source", source_id=self.source_id, url=page_url)
                break

            deal_rows = soup.select(row_selector)

            if not deal_rows:
                break

            for row in deal_rows:
                # 공지/베스트 행은 매일 변하지 않으므로 수집에서 제외
                row_classes = row.get("class") or []
                if isinstance(row_classes, str):
                    row_classes = [row_classes]
                if "bo_notice" in row_classes:
                    continue

                item = self._parse_deal(row)
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
            logger.error("html_fetch_failed", source_id=self.source_id, url=url, error=str(e))
            raise

    def _parse_deal(self, row: Tag) -> RawItem | None:
        """게시물 행에서 상품 정보 추출 (gnuboard5 기준)"""
        title_elem = row.select_one("td.td_subject a[href*='wr_id=']")
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        # 댓글수 sound_only 텍스트가 따라붙는 경우 정리
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            return None

        deal_href_value = title_elem.get("href")
        if not isinstance(deal_href_value, str) or not deal_href_value:
            return None
        deal_href = deal_href_value

        # `//www.dealbada.com/...` 형식의 protocol-relative URL 보정
        if deal_href.startswith("//"):
            deal_url = "https:" + deal_href
        else:
            deal_url = urljoin(self.base_url, deal_href)

        wr_id_match = re.search(r"wr_id=(\d+)", deal_href)
        deal_id = wr_id_match.group(1) if wr_id_match else None

        if not deal_id:
            deal_id = self._generate_product_id(deal_url)

        product_id = f"dealbada_{deal_id}"

        # 카테고리: <td class="td_cate"> 내부 <a class="bo_cate_link">
        category_elem = row.select_one("td.td_cate a.bo_cate_link, td.td_cate a")
        category = category_elem.get_text(strip=True) if category_elem else "기타"

        # 이미지: <td class="td_img"> 내부 img
        image_url: str | None = None
        image_elem = row.select_one("td.td_img img")
        if image_elem:
            raw_image_url = image_elem.get("src") or image_elem.get("data-src")
            if isinstance(raw_image_url, str) and raw_image_url:
                if raw_image_url.startswith("//"):
                    image_url = "https:" + raw_image_url
                else:
                    image_url = urljoin(self.base_url, raw_image_url)

        # 쇼핑몰 추출: 딜바다 제목 컨벤션 `[쇼핑몰] 상품명 (가격 / 배송)`
        shop_name = "기타"
        shop_match = re.match(r"\s*\[([^\]]+)\]", title)
        if shop_match:
            shop_name = shop_match.group(1).strip() or "기타"

        # 가격 추출: 제목 끝의 `(가격원 / 배송)` 패턴 우선, 실패 시 일반 패턴 fallback
        current_price = self._extract_price_from_title(title)

        return RawItem(
            product_id=product_id,
            title=title,
            url=deal_url,
            source=self.source_id,
            collected_at=datetime.now(tz=UTC),
            current_price=current_price,
            list_price=None,
            discount_rate=None,
            category=category,
            platform=shop_name,
            image_url=image_url,
            raw_data={
                "deal_id": deal_id,
                "shop_name": shop_name,
                "category": category,
            },
        )

    def _extract_price_from_title(self, title: str) -> int | None:
        """제목에서 가격 정보 추출 (딜바다 규약 우선).

        주의: BaseCollector._parse_price_value 는 콤마를 공백으로 치환하므로
        `548,000` 같은 입력을 그대로 넘기면 `548` 만 잡힌다. 따라서 콤마를
        먼저 제거한 후 순수 정수 문자열을 넘긴다.
        """

        def _to_int(raw: str) -> int | None:
            digits = raw.replace(",", "").strip()
            if not digits.isdigit():
                return None
            return self._parse_price_value(digits)

        # 1) `(548,000원 / 무료)` 패턴
        paren_match = re.search(r"\(([^)]*?원[^)]*)\)", title)
        if paren_match:
            inner = paren_match.group(1)
            price_match = re.search(r"(\d[\d,]*)\s*원", inner)
            if price_match:
                parsed = _to_int(price_match.group(1))
                if parsed is not None:
                    return parsed
            # `212만원` 같은 단위 표기
            man_match = re.search(r"(\d[\d,]*)\s*만\s*원", inner)
            if man_match:
                man_value = _to_int(man_match.group(1))
                if man_value is not None:
                    return man_value * 10000

        # 2) 본문에 `212만원` 단위 표기 (전체 제목)
        man_match_global = re.search(r"(\d[\d,]*)\s*만\s*원", title)
        if man_match_global:
            man_value = _to_int(man_match_global.group(1))
            if man_value is not None:
                return man_value * 10000

        # 3) 본문에 단순 `123,000원` 패턴
        bare_match = re.search(r"(\d[\d,]*)\s*원", title)
        if bare_match:
            parsed = _to_int(bare_match.group(1))
            if parsed is not None:
                return parsed

        # 4) 통화 기호 패턴
        currency_patterns = [r"₩\s*(\d[\d,]*)", r"(\d[\d,]*)\s*\/"]
        for pattern in currency_patterns:
            match = re.search(pattern, title)
            if match:
                parsed = _to_int(match.group(1))
                if parsed is not None:
                    return parsed

        return None

    def _generate_product_id(self, url: str) -> str:
        """URL 기반 상품 ID 생성"""
        return hashlib.md5(url.encode()).hexdigest()[:12]
