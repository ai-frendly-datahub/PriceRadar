from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from priceradar.mcp_server.tools import (
    handle_price_watch,
    handle_recent_updates,
    handle_search,
    handle_sql,
    handle_top_trends,
)
from priceradar.search_index import SearchIndex


def _seed_db(db_path: Path) -> None:
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE products (
                product_id VARCHAR PRIMARY KEY,
                title VARCHAR NOT NULL,
                url VARCHAR NOT NULL,
                category VARCHAR,
                brand VARCHAR,
                platform VARCHAR,
                image_url VARCHAR,
                first_seen TIMESTAMP,
                last_updated TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE price_snapshots (
                snapshot_id INTEGER,
                product_id VARCHAR,
                ts TIMESTAMP,
                current_price INTEGER,
                avg_price INTEGER,
                list_price INTEGER,
                discount_rate DOUBLE,
                source VARCHAR,
                is_hotdeal BOOLEAN,
                is_popular BOOLEAN,
                is_lowest_now BOOLEAN
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE price_scores (
                score_id INTEGER,
                product_id VARCHAR,
                ts TIMESTAMP,
                radar_score DOUBLE,
                discount_strength DOUBLE,
                timing_rarity DOUBLE,
                popularity DOUBLE,
                volatility DOUBLE,
                saving_amount INTEGER,
                explanation VARCHAR
            )
            """
        )

        conn.execute(
            """
            INSERT INTO products(product_id, title, url, category, brand, platform, first_seen, last_updated)
            VALUES
            ('p1', '닌텐도 스위치 OLED', 'https://shop/p1', 'game', 'Nintendo', 'enuri', now(), now()),
            ('p2', 'Apple Watch', 'https://shop/p2', 'wearable', 'Apple', 'fallcent', now(), now())
            """
        )
        conn.execute(
            """
            INSERT INTO price_snapshots(snapshot_id, product_id, ts, current_price, avg_price, list_price, discount_rate, source, is_hotdeal, is_popular, is_lowest_now)
            VALUES
            (1, 'p1', now() - INTERVAL '2 day', 420000, 450000, 500000, 0.16, 'enuri', true, true, false),
            (2, 'p1', now() - INTERVAL '1 day', 390000, 450000, 500000, 0.22, 'enuri', true, true, true),
            (3, 'p2', now() - INTERVAL '1 day', 470000, 500000, 550000, 0.15, 'fallcent', false, true, false)
            """
        )
        conn.execute(
            """
            INSERT INTO price_scores(score_id, product_id, ts, radar_score, discount_strength, timing_rarity, popularity, volatility, saving_amount, explanation)
            VALUES
            (1, 'p1', now() - INTERVAL '1 day', 0.92, 0.8, 1.0, 1.0, 0.1, 60000, 'best deal'),
            (2, 'p2', now() - INTERVAL '1 day', 0.65, 0.5, 0.5, 0.7, 0.2, 30000, 'good deal')
            """
        )


@pytest.mark.unit
def test_handle_search_uses_nl_parser_and_fts(tmp_path) -> None:
    db_path = tmp_path / "priceradar.duckdb"
    _seed_db(db_path)

    search_db = tmp_path / "search_index.db"
    index = SearchIndex(search_db)
    index.upsert("https://shop/p1", "닌텐도 스위치 OLED", "enuri game Nintendo")

    result = handle_search(
        search_db_path=search_db, db_path=db_path, query="최근 3일 닌텐도 5개", limit=20
    )
    payload = json.loads(result)

    assert payload["days"] == 3
    assert payload["limit"] == 5
    assert payload["results"][0]["link"] == "https://shop/p1"


@pytest.mark.unit
def test_handle_recent_updates_returns_latest_snapshots(tmp_path) -> None:
    db_path = tmp_path / "priceradar.duckdb"
    _seed_db(db_path)

    result = handle_recent_updates(db_path=db_path, days=3, limit=5)
    payload = json.loads(result)

    assert payload["results"]
    assert payload["results"][0]["title"] in {"닌텐도 스위치 OLED", "Apple Watch"}


@pytest.mark.unit
def test_handle_sql_allows_select_only(tmp_path) -> None:
    db_path = tmp_path / "priceradar.duckdb"
    _seed_db(db_path)

    blocked = json.loads(handle_sql(db_path=db_path, query="DELETE FROM products"))
    allowed = json.loads(
        handle_sql(db_path=db_path, query="SELECT title FROM products ORDER BY title")
    )

    assert blocked["ok"] is False
    assert allowed["ok"] is True
    assert len(allowed["rows"]) == 2


@pytest.mark.unit
def test_handle_top_trends_returns_biggest_changes(tmp_path) -> None:
    db_path = tmp_path / "priceradar.duckdb"
    _seed_db(db_path)

    result = handle_top_trends(db_path=db_path, days=7, limit=5)
    payload = json.loads(result)

    assert payload["results"]
    assert payload["results"][0]["title"] == "닌텐도 스위치 OLED"
    assert payload["results"][0]["price_change"] == -30000


@pytest.mark.unit
def test_handle_price_watch_filters_by_min_score(tmp_path) -> None:
    db_path = tmp_path / "priceradar.duckdb"
    _seed_db(db_path)

    result = handle_price_watch(db_path=db_path, min_score=0.8, limit=10)
    payload = json.loads(result)

    assert len(payload["results"]) == 1
    assert payload["results"][0]["title"] == "닌텐도 스위치 OLED"


@pytest.mark.unit
def test_handle_sql_catches_invalid_sql_exception(tmp_path) -> None:
    """line 88-89: SQL 실행 예외 처리"""
    db_path = tmp_path / "priceradar.duckdb"
    _seed_db(db_path)

    result = handle_sql(db_path=db_path, query="SELECT * FROM nonexistent_table")
    payload = json.loads(result)

    assert payload["ok"] is False
    assert "error" in payload


@pytest.mark.unit
def test_is_read_only_query_rejects_empty_string(tmp_path) -> None:
    """line 203: _is_read_only_query에 빈 문자열 전달"""
    db_path = tmp_path / "priceradar.duckdb"
    _seed_db(db_path)

    result = handle_sql(db_path=db_path, query="   ")
    payload = json.loads(result)

    assert payload["ok"] is False
    assert "Only SELECT/WITH/EXPLAIN" in payload["error"]


@pytest.mark.unit
def test_is_read_only_query_rejects_multi_statement(tmp_path) -> None:
    """line 206: 세미콜론이 중간에 있는 SQL (multi-statement)"""
    db_path = tmp_path / "priceradar.duckdb"
    _seed_db(db_path)

    result = handle_sql(db_path=db_path, query="SELECT * FROM products; DELETE FROM products")
    payload = json.loads(result)

    assert payload["ok"] is False
    assert "Only SELECT/WITH/EXPLAIN" in payload["error"]
