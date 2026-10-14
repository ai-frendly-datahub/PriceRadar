from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from priceradar.analyzers.price_scorer import PriceScore
from priceradar.collection_contract import (
    PRICERADAR_USER_AGENT,
    REQUEST_TIMEOUT_SECONDS,
    EmptyCollectionError,
    EmptyOutputError,
    OversizedDatabaseError,
    emit_missing_secret_warning,
    ensure_collection_not_empty,
    ensure_database_within_limit,
    ensure_nonempty_files,
    infer_stock_status,
    is_challenge_or_error_page,
    missing_required_env,
    reset_missing_secret_warnings,
)
from priceradar.collectors.base import RawItem
from priceradar.collectors.html_collector import HtmlCollector
from priceradar.exceptions import ChallengePageError
from priceradar.graph.graph_store import GraphStore, prepare_price_database
from priceradar.raw_logger import RawLogger
from tests.reference_dates import REFERENCE_NOW

_CHALLENGE = Path("tests/fixtures/challenge_page.html").read_text(encoding="utf-8")


@pytest.mark.unit
def test_reference_clock_is_fixed() -> None:
    assert REFERENCE_NOW == datetime(2026, 3, 13, 12, 0, tzinfo=UTC)
    assert REFERENCE_NOW.date().isoformat() == "2026-03-13"


@pytest.mark.unit
def test_http_get_uses_identifying_user_agent_timeout_and_tls() -> None:
    collector = HtmlCollector("unit", {"url": "https://example.com", "selectors": {}})
    recorded: dict[str, object] = {}

    def _get(*_args: object, **kwargs: object) -> Mock:
        recorded.update(kwargs)
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.text = "<title>Contract item</title><p>10000원</p>"
        response.raise_for_status.return_value = None
        return response

    with patch("priceradar.collectors.base.requests.get", side_effect=_get):
        response = collector.http_get("https://example.com/item")

    assert response.text.startswith("<title>Contract item</title>")
    assert recorded["verify"] is True
    assert recorded["timeout"] == REQUEST_TIMEOUT_SECONDS
    headers = recorded["headers"]
    assert isinstance(headers, dict)
    assert headers["User-Agent"] == PRICERADAR_USER_AGENT
    assert str(headers["User-Agent"]).startswith("PriceRadar/0.1")
    assert "Mozilla" not in str(headers["User-Agent"])
    assert collector._session.verify is True
    assert collector._session.headers["User-Agent"] == PRICERADAR_USER_AGENT


@pytest.mark.unit
def test_http_get_rejects_challenge_page_without_sample_items() -> None:
    collector = HtmlCollector("unit", {"url": "https://example.com", "selectors": {}})

    def _get(*_args: object, **_kwargs: object) -> Mock:
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.text = _CHALLENGE
        return response

    with patch("priceradar.collectors.base.requests.get", side_effect=_get):
        with pytest.raises(ChallengePageError):
            collector.http_get("https://www.algumon.com/n/deal")

    with patch(
        "priceradar.collectors.html_collector.HtmlCollector._fetch_html",
        side_effect=requests.exceptions.ConnectionError("down"),
    ):
        assert collector.collect() == []


@pytest.mark.unit
def test_challenge_marker_detects_cloudflare_and_cookie_wall() -> None:
    assert is_challenge_or_error_page("Just a moment...", _CHALLENGE) is True
    assert is_challenge_or_error_page("삼성 모니터", "199000원") is False


@pytest.mark.unit
def test_missing_secret_warns_once_and_records_names_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reset_missing_secret_warnings()
    source = {
        "id": "keyed",
        "required_env": ["PRICERADAR_TEST_TOKEN", "PRICERADAR_TEST_SECRET"],
    }
    with patch.dict(
        os.environ,
        {
            "PRICERADAR_TEST_TOKEN": "",
            "PRICERADAR_TEST_SECRET": "   ",
            "DECOY_SECRET": "super-secret-value",
        },
        clear=False,
    ):
        missing = missing_required_env(source)
        emit_missing_secret_warning("keyed", missing)
        emit_missing_secret_warning("keyed", missing)
        logger = RawLogger(tmp_path, now=REFERENCE_NOW)
        skip_path = logger.log_skip(source_name="keyed", required_env=missing)

    warning = capsys.readouterr().out
    assert warning.count("::warning title=PriceRadar missing secret::") == 1
    assert "PRICERADAR_TEST_TOKEN" in warning
    assert "PRICERADAR_TEST_SECRET" in warning
    assert "super-secret-value" not in warning
    assert skip_path.parent.name == "2026-03-13"
    assert skip_path.name == "keyed.skip.json"
    text = skip_path.read_text(encoding="utf-8")
    assert "PRICERADAR_TEST_TOKEN" in text
    assert "super-secret-value" not in text


@pytest.mark.unit
def test_empty_collection_and_output_gates(tmp_path: Path) -> None:
    with pytest.raises(EmptyCollectionError):
        ensure_collection_not_empty(collected_count=0, enabled_source_count=2)
    ensure_collection_not_empty(collected_count=3, enabled_source_count=2)
    ensure_collection_not_empty(collected_count=0, enabled_source_count=0)

    empty = tmp_path / "price_20260313_summary.json"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(EmptyOutputError):
        ensure_nonempty_files([empty])

    database = tmp_path / "priceradar.duckdb"
    database.write_bytes(b"x" * 32)
    with pytest.raises(OversizedDatabaseError):
        ensure_database_within_limit(database, limit_bytes=16)
    ensure_database_within_limit(database, limit_bytes=64)


@pytest.mark.unit
def test_infer_stock_status_uses_sold_out_markers_and_observed_price() -> None:
    assert infer_stock_status("[품절/네이버] PS5", 64000) == "out_of_stock"
    assert infer_stock_status("(품절)PS5 제로", 44800) == "out_of_stock"
    assert infer_stock_status("일시품절 모니터", 1000) == "out_of_stock"
    assert infer_stock_status("망설이면 품절 반팔티", 4860) == "in_stock"
    assert infer_stock_status("품절대란 비닐봉투", 2000) == "in_stock"
    assert infer_stock_status("페어리 밀폐용기", 5010) == "in_stock"
    assert infer_stock_status("가격 없는 글", None) is None


@pytest.mark.unit
def test_graph_store_derives_effective_price_and_keeps_one_score(tmp_path: Path) -> None:
    store = GraphStore(str(tmp_path / "price.duckdb"))
    priced = RawItem(
        product_id="sku-priced",
        title="페어리 밀폐용기",
        url="https://example.com/priced",
        source="unit",
        collected_at=REFERENCE_NOW,
        current_price=10_000,
    )
    sold_out = RawItem(
        product_id="sku-sold",
        title="[품절] 컨트롤러",
        url="https://example.com/sold",
        source="unit",
        collected_at=REFERENCE_NOW,
        current_price=52_800,
    )
    unpriced = RawItem(
        product_id="sku-open",
        title="가격 미표기",
        url="https://example.com/open",
        source="unit",
        collected_at=REFERENCE_NOW,
    )
    store.save_raw_item(priced)
    store.save_raw_item(sold_out)
    store.save_raw_item(unpriced)
    for index in range(3):
        store.save_price_score(
            PriceScore(
                product_id="sku-priced",
                radar_score=0.5 + index / 10,
                discount_strength=0.4,
                timing_rarity=0.3,
                popularity=0.2,
                volatility=0.1,
                current_price=10_000,
                avg_price=12_000,
                saving_amount=2_000,
                explanation="latest wins",
            )
        )

    priced_row = store.conn.execute("""
        SELECT discount_price, effective_price, stock_status
        FROM price_snapshots WHERE product_id = 'sku-priced'
        """).fetchone()
    sold_row = store.conn.execute(
        "SELECT stock_status FROM price_snapshots WHERE product_id = 'sku-sold'"
    ).fetchone()
    open_row = store.conn.execute("""
        SELECT effective_price, stock_status
        FROM price_snapshots WHERE product_id = 'sku-open'
        """).fetchone()
    score_count = store.conn.execute(
        "SELECT COUNT(*), MAX(radar_score) FROM price_scores WHERE product_id = 'sku-priced'"
    ).fetchone()
    store.close()

    assert priced_row == (10_000, 10_000, "in_stock")
    assert sold_row == ("out_of_stock",)
    assert open_row == (None, None)
    assert score_count == (1, pytest.approx(0.7))


@pytest.mark.unit
def test_prepare_price_database_keeps_latest_score_and_rewrites(tmp_path: Path) -> None:
    db_path = tmp_path / "priceradar.duckdb"
    store = GraphStore(str(db_path))
    store.save_raw_item(
        RawItem(
            product_id="sku-1",
            title="계약 상품",
            url="https://example.com/sku-1",
            source="unit",
            collected_at=REFERENCE_NOW,
            current_price=9_000,
        )
    )
    store.conn.execute("""
        INSERT INTO price_scores (
            product_id, ts, radar_score, discount_strength, timing_rarity,
            popularity, volatility, saving_amount, explanation
        ) VALUES
            ('sku-1', '2026-03-01 00:00:00', 0.2, 0.2, 0.2, 0.2, 0.2, 1, 'old'),
            ('sku-1', '2026-03-13 00:00:00', 0.9, 0.9, 0.9, 0.9, 0.1, 2, 'new')
        """)
    store.conn.execute("""
        UPDATE price_snapshots
        SET discount_price = NULL, effective_price = NULL, stock_status = NULL
        WHERE product_id = 'sku-1'
        """)
    store.close()

    result = prepare_price_database(db_path)

    assert result["prepared"] is True
    assert result["scores_removed"] == 1
    assert int(result["rows_backfilled"]) >= 1
    check = GraphStore(str(db_path))
    try:
        scores = check.conn.execute(
            "SELECT explanation FROM price_scores ORDER BY explanation"
        ).fetchall()
        fields = check.conn.execute("""
            SELECT discount_price, effective_price, stock_status
            FROM price_snapshots WHERE product_id = 'sku-1'
            """).fetchone()
    finally:
        check.close()
    assert scores == [("new",)]
    assert fields == (9_000, 9_000, "in_stock")
