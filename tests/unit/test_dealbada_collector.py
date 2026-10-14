from __future__ import annotations

import pytest

from priceradar.collectors.dealbada_collector import DealbadaCollector


def _board_row(wr_id: str, title: str) -> str:
    return (
        "<table><tbody><tr>"
        "<td class='td_subject'>"
        f"<a href='/bbs/board.php?bo_table=deal_domestic&wr_id={wr_id}'>{title}</a>"
        "</td></tr></tbody></table>"
    )


def test_dealbada_default_timeout_covers_slow_last_page() -> None:
    collector = DealbadaCollector("dealbada_main", {"request_delay": 0, "max_pages": 1})
    assert collector.timeout == 45


def test_dealbada_continues_after_a_page_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = DealbadaCollector(
        "dealbada_main",
        {"request_delay": 0, "max_pages": 3, "max_items": 10},
    )
    fetched: list[str] = []

    def fake_fetch(url: str) -> str:
        fetched.append(url)
        if "page=2" in url:
            raise TimeoutError("Read timed out. (read timeout=30)")
        wr_id = "101" if "page=1" in url else "303"
        return _board_row(wr_id, f"[쿠팡] 상품{wr_id} (12,000원 / 무료)")

    monkeypatch.setattr(collector, "_fetch_html", fake_fetch)

    items = collector.collect()

    assert [url.rsplit("page=", 1)[-1] for url in fetched] == ["1", "2", "3"]
    assert [item.product_id for item in items] == ["dealbada_101", "dealbada_303"]
