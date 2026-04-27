from __future__ import annotations

from datetime import date
from pathlib import Path


def test_snapshot_database_uses_nested_snapshot_contract(tmp_path: Path) -> None:
    from priceradar.date_storage import snapshot_database

    db_path = tmp_path / "data" / "priceradar.duckdb"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("price-db")

    result = snapshot_database(db_path, snapshot_date=date(2026, 4, 12))

    assert result == tmp_path / "data" / "snapshots" / "2026-04-12" / "priceradar.duckdb"
    assert result.read_text() == "price-db"


def test_cleanup_snapshots_removes_old_dated_directories(tmp_path: Path) -> None:
    from priceradar.date_storage import cleanup_snapshots

    old_snapshot = tmp_path / "2026-01-01" / "priceradar.duckdb"
    old_snapshot.parent.mkdir(parents=True)
    old_snapshot.write_text("old")
    recent_snapshot = tmp_path / "2026-04-11" / "priceradar.duckdb"
    recent_snapshot.parent.mkdir(parents=True)
    recent_snapshot.write_text("recent")

    removed = cleanup_snapshots(tmp_path, keep_days=30, today=date(2026, 4, 12))

    assert removed == 1
    assert not old_snapshot.parent.exists()
    assert recent_snapshot.exists()


def test_storage_create_daily_snapshot_uses_snapshot_contract(tmp_path: Path) -> None:
    from priceradar.storage import RadarStorage

    db_path = tmp_path / "data" / "priceradar.duckdb"
    storage = RadarStorage(db_path)
    try:
        result = storage.create_daily_snapshot(snapshot_date=date(2026, 4, 12))
    finally:
        storage.close()

    assert result == tmp_path / "data" / "snapshots" / "2026-04-12" / "priceradar.duckdb"
    assert result.exists()


def test_apply_date_storage_policy_cleans_snapshot_retention(tmp_path: Path) -> None:
    from priceradar.date_storage import apply_date_storage_policy

    db_path = tmp_path / "data" / "priceradar.duckdb"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("price-db")
    old_snapshot = tmp_path / "data" / "snapshots" / "2026-01-01" / "priceradar.duckdb"
    old_snapshot.parent.mkdir(parents=True)
    old_snapshot.write_text("old")

    result = apply_date_storage_policy(
        database_path=db_path,
        raw_data_dir=tmp_path / "data" / "raw",
        report_dir=tmp_path / "reports",
        keep_raw_days=180,
        keep_report_days=90,
        keep_snapshot_days=30,
        snapshot_db=False,
    )

    assert result["snapshots_removed"] == 1
    assert not old_snapshot.parent.exists()
