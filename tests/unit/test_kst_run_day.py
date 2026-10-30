"""One run keeps a single Asia/Seoul date across the UTC/KST midnight window.

00:00-08:59 KST is still the previous UTC date. Dedupe, raw partitions,
snapshots, and dated reports must all use the KST date, so a run in that
window writes one ``price_YYYYMMDD`` stamp.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from priceradar.collectors.base import RawItem
from priceradar.graph.graph_store import GraphStore, _snapshot_calendar_day
from priceradar.pipeline import _calendar_day, run_pipeline
from priceradar.run_date import run_calendar_day


_STAMP = re.compile(r"price_(\d{8})")

# Instants inside 00:00-08:59 KST, where the UTC date is the previous day.
_WINDOW = [
    datetime(2026, 10, 29, 15, 0, tzinfo=UTC),  # 2026-10-30 00:00 KST
    datetime(2026, 10, 29, 15, 47, tzinfo=UTC),  # 2026-10-30 00:47 KST
    datetime(2026, 10, 29, 23, 59, tzinfo=UTC),  # 2026-10-30 08:59 KST
    datetime(2026, 4, 13, 18, 30, tzinfo=UTC),  # 2026-04-14 03:30 KST
]


def _kst(moment: datetime) -> date:
    return run_calendar_day(moment)


def _item(product_id: str, url: str, when: datetime, *, price: int = 12_000) -> RawItem:
    return RawItem(
        product_id=product_id,
        title="무선 이어폰",
        url=url,
        source="unit",
        collected_at=when,
        current_price=price,
        category="electronics",
        platform="example",
    )


@pytest.mark.unit
@pytest.mark.parametrize("moment", _WINDOW, ids=["0000kst", "0047kst", "0859kst", "0330kst"])
def test_calendar_day_follows_kst_through_utc_midnight(moment: datetime) -> None:
    expected = _kst(moment)
    assert expected != moment.astimezone(UTC).date()
    assert _calendar_day(moment) == expected
    assert _snapshot_calendar_day(moment) == expected
    naive = moment.replace(tzinfo=None)
    assert _calendar_day(naive) == expected
    assert _snapshot_calendar_day(naive) == expected


@pytest.mark.unit
@pytest.mark.parametrize("moment", _WINDOW, ids=["0000kst", "0047kst", "0859kst", "0330kst"])
def test_graph_dedupe_uses_kst_not_the_shared_utc_date(moment: datetime, tmp_path: Path) -> None:
    url = "https://example.com/p/1"
    previous = moment - timedelta(hours=9)
    assert previous.astimezone(UTC).date() == moment.astimezone(UTC).date()
    assert _kst(previous) != _kst(moment)

    store = GraphStore(str(tmp_path / "price.duckdb"))
    try:
        assert store.save_raw_item(_item("sku-prev", url, previous, price=20_000))
        assert store.urls_collected_on(_kst(previous)) == {url}
        assert store.urls_collected_on(_kst(moment)) == set()
        assert store.urls_collected_on(moment.astimezone(UTC).date()) == {url}
        assert store.save_raw_item(_item("sku-now", url, moment, price=15_000))
        later = moment + timedelta(hours=8)
        assert _kst(later) == _kst(moment)
        assert not store.save_raw_item(_item("sku-later", url, later, price=14_000))
        count = store.conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()
        assert count == (2,)
    finally:
        store.close()


@pytest.mark.unit
def test_pipeline_keeps_url_when_utc_day_matches_and_kst_day_does_not(tmp_path: Path) -> None:
    db_path = tmp_path / "price.duckdb"
    evening = {
        "product_id": "prev",
        "title": "이전",
        "product_url": "https://example.com/p/1",
        "price": 20000,
        "timestamp": "2026-10-29T14:30:00+00:00",  # 2026-10-29 23:30 KST
    }
    after_midnight = {
        "product_id": "now",
        "title": "자정 이후",
        "product_url": "https://example.com/p/1",
        "price": 15000,
        "timestamp": "2026-10-29T15:47:00+00:00",  # 2026-10-30 00:47 KST
    }
    same_kst_morning = {
        "product_id": "later",
        "title": "같은 KST 날",
        "product_url": "https://example.com/p/1",
        "price": 14000,
        "timestamp": "2026-10-30T00:30:00+00:00",  # 2026-10-30 09:30 KST
    }

    assert run_pipeline([evening, after_midnight], db_path=db_path) == (2, 2, 2)
    assert run_pipeline([same_kst_morning], db_path=db_path) == (0, 0, 0)


def _dated_stamps(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    found: set[str] = set()
    for path in directory.rglob("*"):
        if path.is_file():
            match = _STAMP.search(path.name)
            if match:
                found.add(match.group(1))
    return found


def _directory_dates(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    return {child.name for child in directory.iterdir() if child.is_dir()}


class _ListingCollector:
    def __init__(self, item: RawItem) -> None:
        self._item = item

    def collect(self) -> list[RawItem]:
        return [self._item]


@pytest.mark.unit
@pytest.mark.parametrize("moment", _WINDOW, ids=["0000kst", "0047kst", "0859kst", "0330kst"])
def test_one_run_writes_a_single_kst_report_and_partition(
    moment: datetime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import radar_core.report_utils as report_utils

    from main import run_once

    kst_day = _kst(moment)
    utc_day = moment.astimezone(UTC).date()
    assert kst_day != utc_day

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            if tz is None:
                return moment.replace(tzinfo=None)
            return moment.astimezone(tz)  # type: ignore[arg-type]

    monkeypatch.setattr(report_utils, "datetime", _Frozen)
    monkeypatch.chdir(tmp_path)

    previous = moment - timedelta(hours=9)
    url = "https://example.com/p/1"
    store = GraphStore("data/priceradar.duckdb")
    try:
        assert store.save_raw_item(_item("sku-prev", url, previous, price=20_000))
    finally:
        store.close()

    item = _item("sku-now", url, moment, price=15_000)
    monkeypatch.setattr(
        "main.CollectorRegistry.create_collector",
        lambda source: _ListingCollector(item),
    )

    run_once(
        {
            "database": {"path": "data/priceradar.duckdb"},
            "reporting": {"output_path": "reports", "max_items_per_report": 10},
            "scoring": {},
        },
        {"sources": [{"id": "unit", "enabled": True, "collector_type": "C2_html_simple"}]},
        generate_report_flag=True,
        snapshot_db=True,
        started_at=moment,
    )

    stamp = kst_day.strftime("%Y%m%d")
    assert _dated_stamps(tmp_path / "reports") == {stamp}
    assert (tmp_path / "reports" / f"price_{stamp}.html").is_file()
    assert (tmp_path / "reports" / f"price_{stamp}_summary.json").is_file()
    assert (tmp_path / "reports" / f"price_{stamp}_quality.json").is_file()
    assert not (tmp_path / "reports" / f"price_{utc_day.strftime('%Y%m%d')}.html").exists()
    assert _directory_dates(tmp_path / "data" / "raw") == {kst_day.isoformat()}
    assert _directory_dates(tmp_path / "data" / "snapshots") == {kst_day.isoformat()}

    check = GraphStore("data/priceradar.duckdb")
    try:
        count = check.conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()
        assert count == (2,)
        assert url in check.urls_collected_on(kst_day)
    finally:
        check.close()
