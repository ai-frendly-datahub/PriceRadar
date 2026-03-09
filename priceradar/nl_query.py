from __future__ import annotations
from typing import Optional

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedQuery:
    raw_query: str
    search_text: str
    days: Optional[int]
    limit: int


_KOREAN_DAYS = re.compile(r"(?:최근\s*)?(\d+)\s*일(?:간)?")
_ENGLISH_DAYS = re.compile(r"(?:last|past)\s+(\d+)\s*days?", re.IGNORECASE)
_KOREAN_LIMIT = re.compile(r"(\d+)\s*개")
_ENGLISH_TOP = re.compile(r"top\s+(\d+)", re.IGNORECASE)
_ENGLISH_LIMIT = re.compile(r"limit\s+(\d+)", re.IGNORECASE)


def parse_query(query: str) -> ParsedQuery:
    stripped = query.strip()
    days = _extract_days(stripped)
    limit = _extract_limit(stripped)
    search_text = _clean_query_text(stripped)

    return ParsedQuery(raw_query=query, search_text=search_text, days=days, limit=limit)


def _extract_days(text: str) -> Optional[int]:
    korean_match = _KOREAN_DAYS.search(text)
    if korean_match:
        return int(korean_match.group(1))

    english_match = _ENGLISH_DAYS.search(text)
    if english_match:
        return int(english_match.group(1))

    return None


def _extract_limit(text: str) -> int:
    for pattern in (_KOREAN_LIMIT, _ENGLISH_TOP, _ENGLISH_LIMIT):
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return 20


def _clean_query_text(text: str) -> str:
    cleaned = _KOREAN_DAYS.sub(" ", text)
    cleaned = _ENGLISH_DAYS.sub(" ", cleaned)
    cleaned = _KOREAN_LIMIT.sub(" ", cleaned)
    cleaned = _ENGLISH_TOP.sub(" ", cleaned)
    cleaned = _ENGLISH_LIMIT.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:deals?|show|from|for)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:보여줘|조회|검색)\b", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned
