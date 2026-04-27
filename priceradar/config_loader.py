from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import RadarSettings


def load_settings(config_path: Path | None = None) -> RadarSettings:
    resolve_relative_paths = config_path is None
    if config_path is None:
        config_path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"

    project_root = config_path.resolve().parents[1]
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = raw if isinstance(raw, dict) else {}

    def _get_path(key: str, default: str) -> Path:
        value: Any = config.get(key)
        if value is None and key == "database_path":
            database = config.get("database")
            if isinstance(database, dict):
                value = database.get("path")
        if value is None and key == "report_dir":
            reporting = config.get("reporting")
            if isinstance(reporting, dict):
                value = reporting.get("output_path")
        path = Path(str(value or default))
        if resolve_relative_paths and not path.is_absolute():
            return (project_root / path).resolve()
        return path

    return RadarSettings(
        database_path=_get_path("database_path", "data/priceradar.duckdb"),
        report_dir=_get_path("report_dir", "reports"),
        raw_data_dir=_get_path("raw_data_dir", "data/raw"),
        search_db_path=_get_path("search_db_path", "data/search_index.db"),
    )
