from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from priceradar.collectors.base import RawItem
from priceradar.graph.graph_store import GraphStore
from priceradar.pipeline import dedupe_by_url, run_pipeline


def _item(
    product_id: str,
    url: str,
    *,
    when: datetime,
    price: int = 1000,
) -> RawItem:
    return RawItem(
        product_id=product_id,
        title=product_id,
        url=url,
        source="unit",
        collected_at=when,
        current_price=price,
    )


@pytest.mark.unit
def test_dedupe_by_url_skips_urls_already_seen() -> None:
    when = datetime(2026, 4, 13, 1, 0, tzinfo=UTC)
    seen = {"https://example.com/a"}
    items = [
        _item("a-again", "https://example.com/a", when=when),
        _item("b", "https://example.com/b", when=when),
        _item("b-again", "https://example.com/b", when=when),
        _item("blank-1", "", when=when),
        _item("blank-2", "  ", when=when),
    ]

    kept = dedupe_by_url(items, seen)

    assert [item.product_id for item in kept] == ["b", "blank-1", "blank-2"]
    assert seen == {"https://example.com/a", "https://example.com/b"}


@pytest.mark.unit
def test_save_raw_item_skips_same_day_duplicate_url(tmp_path: Path) -> None:
    store = GraphStore(str(tmp_path / "price.duckdb"))
    day = datetime(2026, 4, 13, 1, 0, tzinfo=UTC)
    try:
        assert store.save_raw_item(_item("sku-1", "https://example.com/p", when=day, price=10_000))
        assert store.save_raw_item(
            _item("sku-other", "https://example.com/other", when=day, price=20_000)
        )
        assert not store.save_raw_item(
            _item("sku-2", "https://example.com/p", when=day + timedelta(hours=8), price=9_000)
        )

        counts = store.conn.execute(
            "SELECT (SELECT COUNT(*) FROM price_snapshots), (SELECT COUNT(*) FROM products)"
        ).fetchone()
        assert counts == (2, 2)
        assert store.urls_collected_on(day.date()) == {
            "https://example.com/p",
            "https://example.com/other",
        }
        assert store.urls_collected_on((day + timedelta(days=1)).date()) == set()
    finally:
        store.close()


@pytest.mark.unit
def test_save_raw_item_skips_naive_timestamps_from_the_same_kst_day(tmp_path: Path) -> None:
    store = GraphStore(str(tmp_path / "price.duckdb"))
    # Naive values are UTC wall time. 15:30 and 23:30 UTC are both 2026-04-14
    # in KST (00:30 and 08:30), inside the 00:00-09:00 KST window.
    early = datetime(2026, 4, 13, 15, 30, tzinfo=UTC).replace(tzinfo=None)
    later = datetime(2026, 4, 13, 23, 30, tzinfo=UTC).replace(tzinfo=None)
    try:
        assert store.save_raw_item(_item("sku-1", "https://example.com/p", when=early))
        assert not store.save_raw_item(
            _item("sku-2", "https://example.com/p", when=later, price=900)
        )
        count = store.conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()
        assert count == (1,)
    finally:
        store.close()


@pytest.mark.unit
def test_save_raw_item_keeps_same_url_on_the_next_day(tmp_path: Path) -> None:
    store = GraphStore(str(tmp_path / "price.duckdb"))
    first = datetime(2026, 4, 13, 9, 0, tzinfo=UTC)
    second = datetime(2026, 4, 14, 9, 0, tzinfo=UTC)
    try:
        assert store.save_raw_item(
            _item("sku-1", "https://example.com/p", when=first, price=10_000)
        )
        assert store.save_raw_item(
            _item("sku-1", "https://example.com/p", when=second, price=8_000)
        )
        count = store.conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()
        assert count == (2,)
    finally:
        store.close()


@pytest.mark.unit
def test_run_pipeline_dedupes_same_day_url_before_insert(tmp_path: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    first = {
        "product_id": "prod_001",
        "title": "First",
        "product_url": "https://example.com/p/1",
        "price": 50000,
        "timestamp": "2026-04-13T01:00:00+00:00",
    }
    duplicate = {
        "product_id": "prod_002",
        "title": "Second",
        "product_url": "https://example.com/p/1",
        "price": 45000,
        "timestamp": "2026-04-13T09:00:00+00:00",
    }
    other = {
        "product_id": "prod_003",
        "title": "Other",
        "product_url": "https://example.com/p/2",
        "price": 30000,
        "timestamp": "2026-04-13T09:00:00+00:00",
    }

    assert run_pipeline([first, duplicate, other], db_path=db_path) == (2, 2, 2)
    assert run_pipeline(
        [
            {
                "product_id": "prod_004",
                "title": "Later same day",
                "product_url": "https://example.com/p/1",
                "price": 40000,
                "timestamp": "2026-04-13T12:00:00+00:00",
            }
        ],
        db_path=db_path,
    ) == (0, 0, 0)
    assert run_pipeline(
        [
            {
                "product_id": "prod_001",
                "title": "Next day",
                "product_url": "https://example.com/p/1",
                "price": 39000,
                "timestamp": "2026-04-14T01:00:00+00:00",
            }
        ],
        db_path=db_path,
    ) == (1, 1, 1)
