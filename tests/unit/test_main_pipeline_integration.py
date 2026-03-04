from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import main
from priceradar.collectors.base import RawItem


@pytest.mark.unit
def test_run_collection_logs_raw_records_and_syncs_search_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw_logs: list[tuple[str, list[dict[str, Any]]]] = []
    upserts: list[tuple[str, str, str]] = []

    class FakeCollector:
        def collect(self) -> list[RawItem]:
            return [
                RawItem(
                    product_id="p-1",
                    title="닌텐도 스위치 OLED",
                    url="https://shop/p1",
                    source="fallcent",
                    platform="fallcent",
                    category="game",
                    brand="Nintendo",
                    current_price=390000,
                    collected_at=datetime(2026, 3, 4, 12, 0, 0),
                )
            ]

    class FakeRegistry:
        @staticmethod
        def create_collector(source: dict[str, object]) -> FakeCollector:
            _ = source
            return FakeCollector()

    class FakeStore:
        def __init__(self, db_path: str) -> None:
            self.db_path = db_path

        def save_raw_item(self, item: RawItem) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeRawLogger:
        def __init__(self, raw_dir: Path) -> None:
            self.raw_dir = raw_dir

        def log(self, records: Any, *, source_name: str) -> Path:
            raw_logs.append((source_name, list(records)))
            return tmp_path / "dummy.jsonl"

    class FakeSearchIndex:
        def __init__(self, db_path: Path) -> None:
            self.db_path = db_path

        def upsert(self, link: str, title: str, body: str) -> None:
            upserts.append((link, title, body))

    monkeypatch.setattr(main, "CollectorRegistry", FakeRegistry)
    monkeypatch.setattr(main, "GraphStore", FakeStore)
    monkeypatch.setattr(main, "RawLogger", FakeRawLogger)
    monkeypatch.setattr(main, "SearchIndex", FakeSearchIndex)

    config = {"database": {"path": str(tmp_path / "priceradar.duckdb")}}
    sources_config = {"sources": [{"id": "fallcent", "enabled": True}]}

    main.run_collection(config, sources_config)

    assert raw_logs
    source_name, records = raw_logs[0]
    assert source_name == "fallcent"
    assert records[0]["product_id"] == "p-1"
    assert upserts == [
        ("https://shop/p1", "닌텐도 스위치 OLED", "fallcent game Nintendo")
    ]
