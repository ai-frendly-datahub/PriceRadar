from __future__ import annotations

"""
Fallcent 페이지를 실제로 크롤링하기 전, 파싱 로직의 틀을 제공하는 스텁입니다.
실제 구현 시:
  - requests/selenium/puppeteer 등으로 HTML을 가져온 뒤
  - BeautifulSoup 등으로 리스트(할인율, 현재가, 평균가, 상품명, 링크, 이미지)를 추출
  - list_type(예: lowest_now, category_drop, popular_now)을 meta에 포함
  - 결과를 pipeline.run_pipeline에 넘길 JSON 구조로 맞추면 됩니다.
"""

from typing import Optional, List, Dict, Any

from bs4 import BeautifulSoup  # type: ignore
import requests


def fetch_fallcent_list(url: str) -> List[Dict[str, Any]]:
    """간단한 HTML 파싱 예시 (실제 선택자는 현장 확인 후 수정 필요)."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items: List[Dict[str, Any]] = []
    for card in soup.select(".product-card"):
        title = (card.select_one(".title") or {}).get_text(strip=True) if card.select_one(".title") else ""
        price_txt = (card.select_one(".price") or {}).get_text(strip=True) if card.select_one(".price") else ""
        avg_txt = (card.select_one(".avg-price") or {}).get_text(strip=True) if card.select_one(".avg-price") else ""
        link_tag = card.select_one("a")
        link = link_tag.get("href") if link_tag else ""
        discount_txt = (card.select_one(".discount") or {}).get_text(strip=True) if card.select_one(".discount") else ""

        items.append(
            {
                "product_id": f"fallcent:{link}",
                "title": title,
                "price": _parse_price(price_txt),
                "avg_price_30d": _parse_price(avg_txt),
                "discount_rate_vs_avg": _parse_pct(discount_txt),
                "product_url": link,
                "source_platform": "coupang",
                "list_type": "category_drop",
            }
        )
    return items


def _parse_price(text: str) -> Optional[int]:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _parse_pct(text: str) -> Optional[float]:
    digits = "".join(ch for ch in text if ch.isdigit() or ch in "-.")
    if not digits:
        return None
    try:
        return float(digits) / 100.0
    except ValueError:
        return None
