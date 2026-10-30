"""One Asia/Seoul calendar date for a PriceRadar run.

Dedupe, raw partitions, database snapshots, and dated report names share
this date. ``price_snapshots.ts`` stays naive UTC wall time. KST is a fixed
UTC+09:00 offset, so the calendar day of a stored timestamp is nine hours
later than the UTC date.
"""

from __future__ import annotations

from radar_core.dates import daily_partition_date as run_calendar_day


# DuckDB TIMESTAMP has no offset. Values are UTC wall time.
SNAPSHOT_KST_DATE_SQL = "CAST(s.ts + INTERVAL 9 HOUR AS DATE)"

__all__ = ["SNAPSHOT_KST_DATE_SQL", "run_calendar_day"]
