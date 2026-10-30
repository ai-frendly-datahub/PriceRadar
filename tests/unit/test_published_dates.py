"""Published instants stay UTC when the crawler timezone is Asia/Seoul."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from priceradar.collector import _extract_datetime, _extract_published
from priceradar.models import Article, Source
from priceradar.quality_report import build_quality_report
from priceradar.raw_logger import RawLogger
from priceradar.storage import RadarStorage


_STRUCT_15UTC = time.struct_time((2026, 10, 28, 15, 0, 0, 2, 301, 0))


def _use_seoul(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Asia/Seoul")
    time.tzset()


def _restore_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()
    time.tzset()


@pytest.mark.unit
def test_feedparser_struct_stores_1500_utc_under_kst(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_seoul(monkeypatch)
    try:
        shifted = datetime.fromtimestamp(time.mktime(_STRUCT_15UTC), tz=UTC)
        assert shifted == datetime(2026, 10, 28, 6, 0, tzinfo=UTC)

        published, raw = _extract_published({"published_parsed": _STRUCT_15UTC})
        updated = _extract_datetime({"updated_parsed": _STRUCT_15UTC})
        assert raw is None
        assert published == datetime(2026, 10, 28, 15, 0, tzinfo=UTC)
        assert updated == datetime(2026, 10, 28, 15, 0, tzinfo=UTC)

        storage = RadarStorage(tmp_path / "priceradar.duckdb")
        try:
            storage.upsert_articles(
                [
                    Article(
                        title="할인",
                        link="https://example.com/deal",
                        summary="",
                        published=published,
                        source="rss",
                        category="price",
                    )
                ]
            )
            row = storage.conn.execute("SELECT published FROM articles").fetchone()
            assert row is not None
            # DuckDB TIMESTAMP is naive UTC wall time.
            assert row[0] == datetime(2026, 10, 28, 15, 0)  # noqa: DTZ001
            loaded = storage.recent_articles("price", days=3650)
            assert loaded[0].published == datetime(2026, 10, 28, 15, 0, tzinfo=UTC)
        finally:
            storage.close()
    finally:
        _restore_tz(monkeypatch)


@pytest.mark.unit
def test_offset_string_keeps_offset_and_stores_utc_wall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_seoul(monkeypatch)
    try:
        published, raw = _extract_published({"published": "Wed, 28 Oct 2026 18:00:00 +0900"})
        assert raw == "Wed, 28 Oct 2026 18:00:00 +0900"
        assert published is not None
        assert published.utcoffset() == timedelta(hours=9)
        assert published.hour == 18
        assert published.astimezone(UTC) == datetime(2026, 10, 28, 9, 0, tzinfo=UTC)

        storage = RadarStorage(tmp_path / "priceradar.duckdb")
        try:
            storage.upsert_articles(
                [
                    Article(
                        title="할인",
                        link="https://example.kr/deal",
                        summary="",
                        published=published,
                        source="rss",
                        category="price",
                        published_raw=raw,
                    )
                ]
            )
            row = storage.conn.execute("SELECT published, published_raw FROM articles").fetchone()
            assert row == (datetime(2026, 10, 28, 9, 0), raw)  # noqa: DTZ001
        finally:
            storage.close()
    finally:
        _restore_tz(monkeypatch)


@pytest.mark.unit
def test_zoneless_string_uses_source_timezone_not_local_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_seoul(monkeypatch)
    try:
        kr = Source(name="매경", type="rss", url="https://www.mk.co.kr/rss/30200046/")
        parsed = _extract_datetime(
            {"published": "2026-10-28 18:00:00", "published_parsed": _STRUCT_15UTC},
            kr,
        )
        assert parsed is not None
        assert parsed.utcoffset() == timedelta(hours=9)
        assert (parsed.year, parsed.month, parsed.day, parsed.hour) == (2026, 10, 28, 18)

        other = Source(name="slick", type="rss", url="https://slickdeals.net/feed")
        utc_parsed = _extract_datetime({"published": "2026-10-28 18:00:00"}, other)
        assert utc_parsed == datetime(2026, 10, 28, 18, 0, tzinfo=UTC)

        explicit = Source(
            name="ny",
            type="rss",
            url="https://example.com/feed",
            default_timezone="America/New_York",
        )
        zoned = _extract_datetime({"published": "2026-07-15 12:00:00"}, explicit)
        assert zoned is not None
        assert zoned.utcoffset() == timedelta(hours=-4)
        assert zoned.hour == 12

        configured = Source(
            name="cfg",
            type="rss",
            url="https://news.example.com/rss",
            config={"default_timezone": "Asia/Seoul"},
        )
        from_config = _extract_datetime({"published": "2026-10-28 18:00:00"}, configured)
        assert from_config is not None
        assert from_config.utcoffset() == timedelta(hours=9)
        assert from_config.hour == 18
        assert from_config != datetime(2026, 10, 28, 18, 0, tzinfo=UTC)
    finally:
        _restore_tz(monkeypatch)


@pytest.mark.unit
def test_daily_partition_uses_kst_collection_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from priceradar import date_storage

    moment = datetime(2026, 10, 28, 15, 30, tzinfo=UTC)
    logger = RawLogger(tmp_path, now=moment)
    path = logger.log(
        [
            Article(
                title="deal",
                link="https://example.com/a",
                summary="",
                published=datetime(2026, 10, 28, 15, 0, tzinfo=UTC),
                source="rss",
                category="price",
            )
        ],
        source_name="rss",
    )
    assert path.parent.name == "2026-10-29"

    report = build_quality_report({"sources": []}, generated_at=moment)
    assert report["target_date"] == "2026-10-29"

    monkeypatch.setattr(
        date_storage, "daily_partition_date", lambda moment=None: date(2026, 10, 29)
    )
    db_path = tmp_path / "priceradar.duckdb"
    db_path.write_text("price-db")
    snapshot = date_storage.snapshot_database(db_path)
    assert snapshot is not None
    assert snapshot.parent.name == "2026-10-29"
