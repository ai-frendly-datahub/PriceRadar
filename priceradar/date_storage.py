from __future__ import annotations

import logging
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def snapshot_database(
    db_path: Path,
    *,
    snapshot_date: date | None = None,
    snapshot_root: Path | None = None,
) -> Path | None:
    if not db_path.exists():
        return None

    target_date = snapshot_date or datetime.now(UTC).date()
    target_root = snapshot_root or db_path.parent / "snapshots"
    target_dir = target_root / target_date.isoformat()
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / db_path.name
    shutil.copy2(db_path, target_path)
    return target_path


def cleanup_date_directories(base_dir: Path, *, keep_days: int, today: date | None = None) -> int:
    if keep_days < 0 or not base_dir.exists():
        return 0

    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=keep_days)
    removed = 0
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            child_date = date.fromisoformat(child.name)
        except ValueError:
            continue

        if child_date < cutoff:
            shutil.rmtree(child)
            removed += 1
    return removed


def cleanup_snapshots(
    snapshot_root: Path,
    *,
    keep_days: int,
    today: date | None = None,
) -> int:
    return cleanup_date_directories(snapshot_root, keep_days=keep_days, today=today)


def cleanup_dated_reports(report_dir: Path, *, keep_days: int, today: date | None = None) -> int:
    if keep_days < 0 or not report_dir.exists():
        return 0

    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=keep_days)
    removed = 0
    for html_file in report_dir.glob("*.html"):
        if html_file.name == "index.html":
            continue

        stamp: date | None = None
        stem = html_file.stem
        if len(stem) >= 8 and stem[-8:].isdigit():
            try:
                stamp = date.fromisoformat(f"{stem[-8:-4]}-{stem[-4:-2]}-{stem[-2:]}")
            except ValueError:
                stamp = None
        elif len(stem) == 10:
            try:
                stamp = date.fromisoformat(stem)
            except ValueError:
                stamp = None

        if stamp is not None and stamp < cutoff:
            html_file.unlink()
            removed += 1
    return removed


def _load_compactor():
    """Return radar-core's DuckDB compactor.

    PriceRadar stores prices in GraphStore, not radar_core.RadarStorage, so
    RadarStorage.close() never compacts this file. The daily workflow commits
    both the live database and the snapshot copy.
    """
    from radar_core.db_compact import compact_duckdb_file

    return compact_duckdb_file


def _compact_database(database_path: Path, *, max_bytes: int | None = None) -> dict[str, object]:
    """Shrink ``database_path`` before it is copied or committed.

    Compaction failure must not block the report or the snapshot. The file
    already on disk is left in place.
    """
    bytes_now = database_path.stat().st_size if database_path.exists() else 0
    fallback: dict[str, object] = {
        "compacted": False,
        "reason": "skipped",
        "bytes": bytes_now,
        "bytes_before": bytes_now,
        "rows_deleted": 0,
    }
    try:
        compact_duckdb_file = _load_compactor()
    except ImportError as exc:
        logger.warning("duckdb_compact_unavailable path=%s error=%s", database_path, exc)
        fallback["reason"] = "unavailable"
        return fallback
    try:
        result = compact_duckdb_file(database_path, max_bytes=max_bytes)
    except Exception as exc:
        logger.warning("duckdb_compact_failed path=%s error=%s", database_path, exc)
        fallback["reason"] = "failed"
        fallback["bytes"] = database_path.stat().st_size if database_path.exists() else 0
        return fallback
    if isinstance(result, dict):
        return result
    fallback["reason"] = "invalid_result"
    return fallback


def apply_date_storage_policy(
    *,
    database_path: Path,
    raw_data_dir: Path,
    report_dir: Path,
    keep_raw_days: int,
    keep_report_days: int,
    snapshot_db: bool,
    keep_snapshot_days: int = 30,
    max_bytes: int | None = None,
) -> dict[str, object]:
    # Compact first so the snapshot is a copy of the file that will be committed.
    compact = _compact_database(database_path, max_bytes=max_bytes)
    snapshot_path = snapshot_database(database_path) if snapshot_db else None
    raw_removed = cleanup_date_directories(raw_data_dir, keep_days=keep_raw_days)
    report_removed = cleanup_dated_reports(report_dir, keep_days=keep_report_days)
    snapshots_removed = cleanup_snapshots(
        database_path.parent / "snapshots",
        keep_days=keep_snapshot_days,
    )
    return {
        "snapshot_path": str(snapshot_path) if snapshot_path is not None else None,
        "raw_removed": raw_removed,
        "report_removed": report_removed,
        "snapshots_removed": snapshots_removed,
        "db_bytes": compact.get("bytes"),
        "db_bytes_before": compact.get("bytes_before"),
        "db_compacted": compact.get("compacted"),
        "db_rows_deleted": compact.get("rows_deleted"),
        "db_reason": compact.get("reason"),
    }
