from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from priceradar.nl_query import parse_query
from priceradar.search_index import SearchIndex


def handle_search(*, search_db_path: Path, db_path: Path, query: str, limit: int = 20) -> str:
    _ = db_path
    parsed = parse_query(query)
    index = SearchIndex(search_db_path)
    results = index.search(
        parsed.search_text or query, limit=parsed.limit if limit == 20 else limit
    )

    payload = {
        "ok": True,
        "query": parsed.search_text,
        "days": parsed.days,
        "limit": parsed.limit if limit == 20 else limit,
        "results": [
            {"link": item.link, "title": item.title, "body": item.body} for item in results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def handle_recent_updates(*, db_path: Path, days: int = 7, limit: int = 20) -> str:
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT p.title, p.url, p.platform, p.category, p.brand,
                   s.current_price, s.avg_price, s.list_price, s.discount_rate, s.ts
            FROM price_snapshots s
            JOIN products p ON p.product_id = s.product_id
            WHERE s.ts >= ?
            ORDER BY s.ts DESC
            LIMIT ?
            """,
            [cutoff, limit],
        ).fetchall()

    payload = {
        "ok": True,
        "days": days,
        "limit": limit,
        "results": [
            {
                "title": row[0],
                "url": row[1],
                "store": row[2],
                "category": row[3],
                "brand": row[4],
                "price": row[5],
                "avg_price": row[6],
                "original_price": row[7],
                "discount_rate": row[8],
                "snapshot_at": row[9],
            }
            for row in rows
        ],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def handle_sql(*, db_path: Path, query: str) -> str:
    sql = query.strip()
    if not _is_read_only_query(sql):
        return json.dumps(
            {
                "ok": False,
                "error": "Only SELECT/WITH/EXPLAIN single-statement queries are allowed.",
            },
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
        {"ok": True, "columns": columns, "rows": rows}, ensure_ascii=False, default=str
    )


def handle_top_trends(*, db_path: Path, days: int = 7, limit: int = 20) -> str:
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    s.product_id,
                    s.current_price,
                    s.ts,
                    ROW_NUMBER() OVER (PARTITION BY s.product_id ORDER BY s.ts DESC) AS rn
                FROM price_snapshots s
                WHERE s.ts >= ?
            ), paired AS (
                SELECT
                    latest.product_id,
                    latest.current_price AS latest_price,
                    prev.current_price AS prev_price,
                    latest.current_price - prev.current_price AS price_change,
                    latest.ts AS latest_ts
                FROM ranked latest
                JOIN ranked prev
                  ON latest.product_id = prev.product_id
                WHERE latest.rn = 1 AND prev.rn = 2
            )
            SELECT p.title, p.url, p.platform, paired.latest_price, paired.prev_price,
                   paired.price_change, paired.latest_ts
            FROM paired
            JOIN products p ON p.product_id = paired.product_id
            ORDER BY ABS(paired.price_change) DESC
            LIMIT ?
            """,
            [cutoff, limit],
        ).fetchall()

    payload = {
        "ok": True,
        "days": days,
        "limit": limit,
        "results": [
            {
                "title": row[0],
                "url": row[1],
                "store": row[2],
                "latest_price": row[3],
                "previous_price": row[4],
                "price_change": row[5],
                "snapshot_at": row[6],
            }
            for row in rows
        ],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def handle_price_watch(*, db_path: Path, min_score: float = 0.0, limit: int = 20) -> str:
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            """
            WITH latest_scores AS (
                SELECT
                    ps.product_id,
                    ps.radar_score,
                    ROW_NUMBER() OVER (PARTITION BY ps.product_id ORDER BY ps.ts DESC) AS rn
                FROM price_scores ps
            ), latest_snapshots AS (
                SELECT
                    snap.product_id,
                    snap.current_price,
                    snap.list_price,
                    snap.discount_rate,
                    ROW_NUMBER() OVER (PARTITION BY snap.product_id ORDER BY snap.ts DESC) AS rn
                FROM price_snapshots snap
            )
            SELECT p.title, p.url, p.platform, ls.radar_score,
                   sn.current_price, sn.list_price, sn.discount_rate
            FROM latest_scores ls
            JOIN products p ON p.product_id = ls.product_id
            JOIN latest_snapshots sn ON sn.product_id = p.product_id
            WHERE ls.rn = 1 AND sn.rn = 1 AND ls.radar_score >= ?
            ORDER BY ls.radar_score DESC
            LIMIT ?
            """,
            [min_score, limit],
        ).fetchall()

    payload = {
        "ok": True,
        "min_score": min_score,
        "limit": limit,
        "results": [
            {
                "title": row[0],
                "url": row[1],
                "store": row[2],
                "radar_score": row[3],
                "price": row[4],
                "original_price": row[5],
                "discount_rate": row[6],
            }
            for row in rows
        ],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _is_read_only_query(query: str) -> bool:
    normalized = query.strip().lower()
    if not normalized:
        return False

    if ";" in normalized.rstrip(";"):
        return False

    return (
        normalized.startswith("select")
        or normalized.startswith("with")
        or normalized.startswith("explain")
    )
