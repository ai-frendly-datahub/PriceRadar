from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from priceradar.nl_query import parse_query
from priceradar.search_index import SearchIndex


def _is_read_only_query(query: str) -> bool:
    normalized = query.strip().lower()
    if not normalized:
        return False
    if ";" in normalized.rstrip(";"):
        return False
    return normalized.startswith(("select", "with", "explain"))


def _links_within_window(db_path: Path, links: list[str], days: int | None) -> set[str]:
    if days is None or not links:
        return set(links)

    cutoff = datetime.now(UTC) - timedelta(days=days)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT link
            FROM articles
            WHERE COALESCE(published, collected_at) >= ?
            """,
            [cutoff],
        ).fetchall()
    recent_links = {str(row[0]) for row in rows}
    return {link for link in links if link in recent_links}


def handle_search(*, search_db_path: Path, db_path: Path, query: str, limit: int = 20) -> str:
    parsed = parse_query(query)
    effective_limit = parsed.limit if limit == 20 else limit
    with SearchIndex(search_db_path) as index:
        results = index.search(parsed.search_text or query, limit=effective_limit)

    allowed_links = _links_within_window(db_path, [result.link for result in results], parsed.days)
    filtered = [result for result in results if result.link in allowed_links]
    return json.dumps(
        {
            "ok": True,
            "query": parsed.search_text,
            "days": parsed.days,
            "limit": effective_limit,
            "results": [
                {"link": result.link, "title": result.title, "body": result.body}
                for result in filtered
            ],
        },
        ensure_ascii=False,
        default=str,
    )


def handle_recent_updates(*, db_path: Path, days: int = 7, limit: int = 20) -> str:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT title, link, source, category, collected_at
            FROM articles
            WHERE COALESCE(published, collected_at) >= ?
            ORDER BY COALESCE(published, collected_at) DESC
            LIMIT ?
            """,
            [cutoff, limit],
        ).fetchall()

    return json.dumps(
        {
            "ok": True,
            "days": days,
            "limit": limit,
            "results": [
                {
                    "title": row[0],
                    "link": row[1],
                    "source": row[2],
                    "category": row[3],
                    "collected_at": row[4],
                }
                for row in rows
            ],
        },
        ensure_ascii=False,
        default=str,
    )


def handle_sql(*, db_path: Path, query: str) -> str:
    sql = query.strip()
    if not _is_read_only_query(sql):
        return json.dumps(
            {"ok": False, "error": "Only SELECT/WITH/EXPLAIN queries are allowed"},
            ensure_ascii=False,
        )

    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return json.dumps(
        {"ok": True, "columns": columns, "rows": rows},
        ensure_ascii=False,
        default=str,
    )


def handle_top_trends(*, db_path: Path, days: int = 7, limit: int = 20) -> str:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT entities_json
            FROM articles
            WHERE COALESCE(published, collected_at) >= ?
            """,
            [cutoff],
        ).fetchall()

    counts: Counter[str] = Counter()
    for (raw_entities,) in rows:
        if not raw_entities:
            continue
        try:
            entities = json.loads(raw_entities)
        except json.JSONDecodeError:
            continue
        if not isinstance(entities, dict):
            continue
        for entity_name, keywords in entities.items():
            if isinstance(keywords, list):
                counts[str(entity_name)] += len(keywords)
            else:
                counts[str(entity_name)] += 1

    return json.dumps(
        {"ok": True, "days": days, "results": counts.most_common(limit)},
        ensure_ascii=False,
    )


def handle_price_watch(*, threshold: float = 0.0) -> str:
    _ = threshold
    return "Not available in template project"
