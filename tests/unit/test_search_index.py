from __future__ import annotations

import pytest

from priceradar.search_index import SearchIndex


@pytest.mark.unit
def test_search_index_upsert_and_search_by_title_and_body(tmp_path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    index.upsert(
        link="https://shop.example/p-1",
        title="닌텐도 스위치 OLED",
        body="enuri game console nintendo",
    )
    index.upsert(
        link="https://shop.example/p-2",
        title="Apple Watch Series",
        body="fallcent wearable apple",
    )

    title_hits = index.search("스위치")
    body_hits = index.search("wearable")

    assert len(title_hits) == 1
    assert title_hits[0].link == "https://shop.example/p-1"
    assert len(body_hits) == 1
    assert body_hits[0].title == "Apple Watch Series"


@pytest.mark.unit
def test_search_index_respects_limit(tmp_path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    index.upsert("https://shop.example/1", "USB C Cable", "electronics")
    index.upsert("https://shop.example/2", "USB C Hub", "electronics")

    hits = index.search("USB", limit=1)

    assert len(hits) == 1
