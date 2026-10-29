from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from radar_core.dates import daily_partition_date, to_utc_iso

from .models import Article


class RawLogger:
    def __init__(self, raw_dir: Path, *, now: datetime | None = None):
        self.raw_dir: Path = raw_dir
        self._now = now

    def _clock(self, now: datetime | None = None) -> datetime:
        return now or self._now or datetime.now(UTC)

    def log_skip(
        self,
        *,
        source_name: str,
        required_env: list[str],
        now: datetime | None = None,
    ) -> Path:
        """Write env var names for a skipped source. Values are never stored."""
        moment = self._clock(now)
        date_dir = self.raw_dir / daily_partition_date(moment).isoformat()
        safe_source_name = source_name.replace("/", "_").replace("\\", "_")
        output_path = date_dir / f"{safe_source_name}.skip.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": source_name,
            "required_env": list(required_env),
            "skipped_at": moment.isoformat(),
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return output_path

    def log(
        self,
        articles: Iterable[Article],
        *,
        source_name: str,
        run_id: str | None = None,
    ) -> Path:
        now = self._clock()
        date_dir = self.raw_dir / daily_partition_date(now).isoformat()
        safe_source_name = source_name.replace("/", "_").replace("\\", "_")

        if run_id is not None:
            output_path = date_dir / f"{safe_source_name}_{run_id}.jsonl"
        else:
            output_path = date_dir / f"{safe_source_name}.jsonl"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        existing_links: set[str] = set()
        if run_id is not None and output_path.exists():
            try:
                with output_path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            record = json.loads(line)
                            existing_links.add(record.get("link", ""))
            except (OSError, json.JSONDecodeError):
                pass

        wrote = 0
        with output_path.open("a", encoding="utf-8") as handle:
            for article in articles:
                if run_id is not None and article.link in existing_links:
                    continue

                record = {
                    "title": article.title,
                    "link": article.link,
                    "summary": article.summary,
                    "published": to_utc_iso(article.published) if article.published else None,
                    "published_raw": article.published_raw,
                    "source": article.source,
                    "category": article.category,
                    "matched_entities": article.matched_entities,
                    "logged_at": to_utc_iso(now),
                }
                _ = handle.write(json.dumps(record, ensure_ascii=False))
                _ = handle.write("\n")
                wrote += 1
                if run_id is not None:
                    existing_links.add(article.link)

        # A zero-byte JSONL fails the daily artifact gate. An empty collection
        # must not leave a placeholder file behind.
        if wrote == 0 and output_path.exists() and output_path.stat().st_size == 0:
            output_path.unlink()

        return output_path
