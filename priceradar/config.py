from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    database_path: Path


def load_settings(*, db_path_override: Path | None = None) -> Settings:
    db_path_env = os.environ.get("PRICERADAR_DB_PATH")
    db_path = Path(db_path_env) if db_path_env else (db_path_override or Path("data/priceradar.duckdb"))
    db_path = db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(database_path=db_path)
