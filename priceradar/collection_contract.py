"""Collection rules shared with the Radar-Template operations contract.

PriceRadar identifies itself, verifies TLS, records missing secrets by name,
and refuses empty or oversized outputs. It does not invent listings.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PRICERADAR_USER_AGENT = "PriceRadar/0.1 (+https://github.com/ai-frendly-datahub/PriceRadar)"
REQUEST_TIMEOUT_SECONDS = 45
# GitHub rejects blobs at or above 100 MiB (1024-based).
GITHUB_FILE_LIMIT_BYTES = 100 * 1024 * 1024

_ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ERROR_PAGE_TITLE_RE = re.compile(
    r"^(?:just a moment|attention required|access denied|403 forbidden|404 not found)\b",
    re.IGNORECASE,
)
# Bracketed or leading "품절" is a sold-out marker. Marketing copy such as
# "망설이면 품절" does not start with that token and stays in stock.
_OUT_OF_STOCK_RE = re.compile(
    r"(?:"
    r"(?:^|[\[\(])\s*품절(?:\s*[\]\)/,]|\s|$)"
    r"|일시품절|판매종료|재고\s*없음|재고소진|품절됨|sold\s*out"
    r")",
    re.IGNORECASE,
)
_WARNED_SOURCES: set[str] = set()


class EmptyCollectionError(RuntimeError):
    """Enabled sources produced no listings."""


class OversizedDatabaseError(RuntimeError):
    """A DuckDB file is at or above GitHub's per-file limit."""


class EmptyOutputError(RuntimeError):
    """A report or data file that should hold rows is 0 bytes."""


def is_challenge_or_error_page(title: str | None, body: str | None = None) -> bool:
    """True when a document is a bot wall or an error page, not a listing.

    TLS stays on. This check drops the page; it does not solve the challenge.
    """
    title_text = (title or "").strip()
    body_text = body or ""
    if title_text and _ERROR_PAGE_TITLE_RE.match(title_text):
        return True

    blob = f"{title_text}\n{body_text}".lower()
    if "just a moment" in blob and (
        "cloudflare" in blob or "security verification" in blob or "verify you are human" in blob
    ):
        return True
    if "attention required" in blob and ("cloudflare" in blob or "been blocked" in blob):
        return True
    if "cf-browser-verification" in blob or "challenges.cloudflare.com" in blob:
        return True
    if "slowaes.decrypt" in blob and "cupid" in blob:
        return True
    if "enable javascript and cookies to continue" in blob:
        return True
    return False


def infer_stock_status(title: str | None, current_price: int | None) -> str | None:
    """Read stock from the listing text, otherwise from a positive price.

    A positive price on a listing that is not marked sold out is ``in_stock``.
    Listings with no price and no sold-out marker stay unknown (``None``).
    """
    if _OUT_OF_STOCK_RE.search(title or ""):
        return "out_of_stock"
    if current_price is not None and current_price > 0:
        return "in_stock"
    return None


def missing_required_env(source: Mapping[str, Any]) -> list[str]:
    """Return required environment variable names that are unset or blank."""
    raw = source.get("required_env")
    if raw is None:
        raw = source.get("required_secrets")
    if isinstance(raw, str):
        candidates = [raw]
    elif isinstance(raw, list):
        candidates = [str(item) for item in raw]
    else:
        candidates = []

    missing: list[str] = []
    for name in candidates:
        cleaned = name.strip()
        if _ENV_VAR_NAME.fullmatch(cleaned) is None:
            continue
        if os.environ.get(cleaned, "").strip():
            continue
        missing.append(cleaned)
    return missing


def emit_missing_secret_warning(source_name: str, names: list[str]) -> None:
    """Warn once. The message contains variable names, never values."""
    if not names or source_name in _WARNED_SOURCES:
        return
    _WARNED_SOURCES.add(source_name)
    joined = ", ".join(names)
    print(
        f"::warning title=PriceRadar missing secret::{source_name} skipped; required env {joined}",
        flush=True,
    )


def reset_missing_secret_warnings() -> None:
    """Clear the once-per-process warning set. Tests use this."""
    _WARNED_SOURCES.clear()


def ensure_collection_not_empty(*, collected_count: int, enabled_source_count: int) -> None:
    """Fail when enabled sources produced nothing.

    A dated copy of an old database is not evidence that this run collected.
    """
    if enabled_source_count > 0 and collected_count <= 0:
        raise EmptyCollectionError("Collection produced no listings from enabled sources")


def ensure_database_within_limit(
    database_path: Path,
    *,
    limit_bytes: int = GITHUB_FILE_LIMIT_BYTES,
) -> None:
    """Fail before git push when a DuckDB file would be rejected."""
    if not database_path.exists():
        return
    size = database_path.stat().st_size
    if size >= limit_bytes:
        raise OversizedDatabaseError(
            f"{database_path} is {size} bytes, at or above GitHub's 100 MiB limit"
        )


def ensure_nonempty_files(paths: list[Path]) -> None:
    """Fail when a generated report or data file is 0 bytes."""
    for path in paths:
        if path.is_file() and path.stat().st_size == 0:
            raise EmptyOutputError(f"{path} is 0 bytes")
