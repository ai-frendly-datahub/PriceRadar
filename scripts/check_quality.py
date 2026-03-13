#!/usr/bin/env python3
"""Run DuckDB data quality checks."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from priceradar.common.quality_checks import check_dates, check_missing_fields, run_all_checks


def main() -> None:
    db_path = PROJECT_ROOT / "data" / "priceradar.duckdb"
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    with duckdb.connect(str(db_path), read_only=True) as con:
        run_all_checks(
            con,
            table_name="products",
            null_conditions={
                "title": "title IS NULL OR title = ''",
                "product_url": "product_url IS NULL OR product_url = ''",
            },
            text_columns=["title"],
            url_column="product_url",
        )

        print("\n" + "=" * 60 + "\n")

        check_missing_fields(
            con,
            table_name="price_snapshots",
            null_conditions={
                "product_id": "product_id IS NULL",
                "price": "price IS NULL",
                "ts": "ts IS NULL",
            },
        )
        check_dates(con, table_name="price_snapshots", date_column="ts")


if __name__ == "__main__":
    main()
