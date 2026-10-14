from __future__ import annotations

from bs4 import BeautifulSoup

from priceradar.collectors.fallcent_collector import FallcentCollector

_HOME_HTML = """
<html><body>
  <a href="/product/recommend/?from=gnb">추천</a>
  <a href="/product/search/?keyword=사이다">검색</a>
  <a href="/product/AbCdEf12/?from=home">
    <img alt="구형 상품" src="/static/old.jpg">
    <p class="line-clamp-2">구형 상품</p>
    <span>9,900원</span>
  </a>
  <a href="https://fcnt.link/token-one">
    <img alt="캔메이크 파우더" src="https://thumbnail.example/a.jpg">
    <p class="line-clamp-2">캔메이크 파우더</p>
    <span class="text-[16px] font-bold">13,490원</span>
  </a>
</body></html>
"""


def test_fallcent_reads_short_links_and_skips_nav() -> None:
    collector = FallcentCollector("fallcent_main", {"category": "all"})
    items = collector._parse_products(BeautifulSoup(_HOME_HTML, "html.parser"))

    by_title = {item.title: item for item in items}
    assert set(by_title) == {"구형 상품", "캔메이크 파우더"}
    assert by_title["구형 상품"].product_id == "fallcent_AbCdEf12"
    assert by_title["구형 상품"].current_price == 9900
    short = by_title["캔메이크 파우더"]
    assert short.product_id.startswith("fallcent_")
    assert short.product_id != "fallcent_token-one"
    assert short.url == "https://fcnt.link/token-one"
    assert short.current_price == 13490
    assert short.platform == "coupang"
