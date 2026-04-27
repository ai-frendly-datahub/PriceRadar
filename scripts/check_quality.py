#!/usr/bin/env python3
"""Run DuckDB data quality checks."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import duckdb
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from priceradar.common.quality_checks import (  # noqa: E402
    check_dates,
    check_missing_fields,
    run_all_checks,
)
from priceradar.graph.graph_store import GraphStore  # noqa: E402
from priceradar.quality_report import (  # noqa: E402
    build_quality_report,
    load_sources_config,
    write_quality_report,
)


def _project_path(project_root: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else project_root / path


def _load_runtime_config(project_root: Path) -> dict[str, Any]:
    raw = yaml.safe_load((project_root / "config" / "config.yaml").read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def _infer_target_date(deal_rows: Iterable[Mapping[str, Any]]) -> date:
    observed_dates = [
        parsed
        for row in deal_rows
        if (parsed := _coerce_date(row.get("collected_at") or row.get("observed_at"))) is not None
    ]
    return max(observed_dates) if observed_dates else datetime.now(UTC).date()


def generate_quality_artifacts(project_root: Path = PROJECT_ROOT) -> tuple[dict[str, str], dict[str, Any]]:
    config = _load_runtime_config(project_root)
    sources_path = project_root / "config" / "sources.yaml"
    sources_config = load_sources_config(sources_path)
    database_path = _project_path(
        project_root,
        str(config.get("database", {}).get("path", "data/priceradar.duckdb")),
    )
    quality_outputs = (
        sources_config.get("data_quality", {}).get("quality_outputs", {})
        if isinstance(sources_config.get("data_quality"), dict)
        else {}
    )
    latest_quality_path = Path(str(quality_outputs.get("latest", "reports/price_quality.json")))
    output_dir = _project_path(project_root, latest_quality_path.parent)
    max_items = int(config.get("reporting", {}).get("max_items_per_report", 100))

    store = GraphStore(str(database_path))
    try:
        deals = store.get_top_deals(limit=max_items)
    finally:
        store.close()

    target_date = _infer_target_date(deals)
    report = build_quality_report(
        sources_config,
        target_date=target_date,
        deal_rows=deals,
    )
    paths = write_quality_report(report, output_dir, target_date=target_date)
    return paths, report


def main() -> None:
    config = _load_runtime_config(PROJECT_ROOT)
    db_path = _project_path(
        PROJECT_ROOT,
        str(config.get("database", {}).get("path", "data/priceradar.duckdb")),
    )
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    with duckdb.connect(str(db_path), read_only=True) as con:
        run_all_checks(
            con,
            table_name="products",
            null_conditions={
                "title": "title IS NULL OR title = ''",
                "url": "url IS NULL OR url = ''",
            },
            text_columns=["title"],
            language_column=None,
            url_column="url",
            date_column="last_updated",
        )

        print("\n" + "=" * 60 + "\n")

        check_missing_fields(
            con,
            table_name="price_snapshots",
            null_conditions={
                "product_id": "product_id IS NULL",
                "current_price": "current_price IS NULL",
                "ts": "ts IS NULL",
            },
        )
        check_dates(con, table_name="price_snapshots", date_column="ts")

    paths, report = generate_quality_artifacts(PROJECT_ROOT)
    summary = report["summary"]
    print(f"quality_report={paths['latest']}")
    print(f"enabled_source_count={summary['enabled_source_count']}")
    print(f"tracked_price_event_count={summary['tracked_price_event_count']}")
    print(f"authority_gap_review_count={summary['authority_gap_review_count']}")
    print(f"official_source_backlog_count={summary['official_source_backlog_count']}")
    print(f"daily_review_item_count={summary['daily_review_item_count']}")


if __name__ == "__main__":
    main()
