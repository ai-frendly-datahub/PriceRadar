"""Fixed clock for tests. Do not assert against datetime.now()."""

from __future__ import annotations

from datetime import UTC, datetime

REFERENCE_NOW = datetime(2026, 3, 13, 12, 0, tzinfo=UTC)
REFERENCE_DATE = REFERENCE_NOW.date()
