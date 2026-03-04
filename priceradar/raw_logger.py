from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


class RawLogger:
    def __init__(self, raw_dir: Path) -> None:
        self.raw_dir = raw_dir

    def log(self, records: Iterable[dict[str, Any]], *, source_name: str) -> Path:
        """Log scraped product data to JSONL."""
        date_dir = self.raw_dir / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        file_path = date_dir / f"{source_name}.jsonl"
        with file_path.open("w", encoding="utf-8") as file_obj:
            for record in records:
                file_obj.write(json.dumps(record, ensure_ascii=False, default=str))
                file_obj.write("\n")

        return file_path
