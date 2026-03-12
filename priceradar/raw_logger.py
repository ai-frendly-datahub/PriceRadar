from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


class RawLogger:
    def __init__(self, raw_dir: Path) -> None:
        self.raw_dir = raw_dir

    def log(
        self,
        records: Iterable[dict[str, Any]],
        *,
        source_name: str,
        run_id: Optional[str] = None,
    ) -> Path:
        """Log scraped product data to JSONL."""
        date_dir = self.raw_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        safe_source_name = source_name.replace("/", "_").replace("\\", "_")
        file_path = (
            date_dir / f"{safe_source_name}_{run_id}.jsonl"
            if run_id is not None
            else date_dir / f"{safe_source_name}.jsonl"
        )

        existing_links: set[str] = set()
        if run_id is not None and file_path.exists():
            try:
                with file_path.open("r", encoding="utf-8") as file_obj:
                    for line in file_obj:
                        if not line.strip():
                            continue
                        record = json.loads(line)
                        link = record.get("link") or record.get("url")
                        if isinstance(link, str) and link:
                            existing_links.add(link)
            except (json.JSONDecodeError, OSError):
                pass

        with file_path.open("a", encoding="utf-8") as file_obj:
            for record in records:
                link = record.get("link") or record.get("url")
                if run_id is not None and isinstance(link, str) and link in existing_links:
                    continue

                file_obj.write(json.dumps(record, ensure_ascii=False, default=str))
                file_obj.write("\n")

                if run_id is not None and isinstance(link, str) and link:
                    existing_links.add(link)

        return file_path
