from __future__ import annotations

import json
from datetime import datetime

import pytest

from priceradar.raw_logger import RawLogger


@pytest.mark.unit
def test_raw_logger_writes_jsonl_to_date_partitioned_path(tmp_path) -> None:
    logger = RawLogger(tmp_path)
    records = [
        {"product_id": "p-1", "title": "Deal A", "price": 9900},
        {"product_id": "p-2", "title": "Deal B", "price": 12900},
    ]

    output_path = logger.log(records, source_name="fallcent")

    expected_dir = tmp_path / datetime.now().strftime("%Y-%m-%d")
    assert output_path == expected_dir / "fallcent.jsonl"
    assert output_path.exists()

    lines = output_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["product_id"] == "p-1"
    assert json.loads(lines[1])["price"] == 12900
