from __future__ import annotations

import json
from datetime import UTC, datetime

import duckdb
import pytest

from main import _deal_matched_entities, generate_report
from priceradar.analyzers.price_scorer import PriceScore
from priceradar.collectors.base import RawItem
from priceradar.graph.graph_store import GraphStore
from priceradar.pipeline import _normalize_snapshot
from priceradar.validators import validate_article


@pytest.mark.unit
def test_validate_article_checks_price_contract_fields() -> None:
    item = RawItem(
        product_id="sku-1",
        title="Contract item",
        url="https://example.com/products/sku-1",
        source="unit",
        current_price=10_000,
        discount_price=9_000,
        coupon_value=500,
        card_benefit=1_000,
        shipping_fee=3_000,
        effective_price=10_500,
        category="electronics",
        platform="example",
    )

    is_valid, errors = validate_article(item)

    assert is_valid is True
    assert errors == []


@pytest.mark.unit
def test_validate_article_rejects_invalid_price_contract_amount() -> None:
    item = RawItem(
        product_id="sku-1",
        title="Contract item",
        url="https://example.com/products/sku-1",
        source="unit",
        current_price=10_000,
        coupon_value=-1,
        category="electronics",
        platform="example",
    )

    is_valid, errors = validate_article(item)

    assert is_valid is False
    assert "coupon_value out of range: -1" in errors


@pytest.mark.unit
def test_normalize_snapshot_preserves_price_contract_meta() -> None:
    snap, product = _normalize_snapshot(
        {
            "product_id": "sku-1",
            "title": "Contract item",
            "current_price": 10_000,
            "avg_price_30d": 12_000,
            "discount_price": 9_000,
            "coupon_value": 500,
            "card_benefit": 1_000,
            "shipping_fee": 3_000,
            "stock_status": "in_stock",
            "option_signature": "default",
            "outlier_flag": True,
        }
    )

    assert product.id == "sku-1"
    assert snap.price == 10_000
    assert snap.discount_rate_vs_avg == pytest.approx(0.1666666667)
    assert snap.meta["discount_price"] == 9_000
    assert snap.meta["coupon_value"] == 500
    assert snap.meta["card_benefit"] == 1_000
    assert snap.meta["shipping_fee"] == 3_000
    assert snap.meta["effective_price"] == 10_500
    assert snap.meta["stock_status"] == "in_stock"
    assert snap.meta["option_signature"] == "default"
    assert snap.meta["outlier_flag"] is True


@pytest.mark.unit
def test_graph_store_adds_contract_columns_to_existing_schema(tmp_path) -> None:
    db_path = tmp_path / "legacy.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE SEQUENCE snapshot_seq START 1")
    conn.execute(
        """
        CREATE TABLE products (
            product_id VARCHAR PRIMARY KEY,
            title VARCHAR NOT NULL,
            url VARCHAR NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE price_snapshots (
            snapshot_id INTEGER PRIMARY KEY DEFAULT nextval('snapshot_seq'),
            product_id VARCHAR NOT NULL,
            ts TIMESTAMP NOT NULL,
            current_price INTEGER,
            avg_price INTEGER,
            list_price INTEGER,
            discount_rate DOUBLE,
            source VARCHAR,
            is_hotdeal BOOLEAN DEFAULT FALSE,
            is_popular BOOLEAN DEFAULT FALSE,
            is_lowest_now BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        )
        """
    )
    conn.execute("CREATE INDEX idx_snapshots_product ON price_snapshots(product_id)")
    conn.execute(
        "INSERT INTO products (product_id, title, url) VALUES (?, ?, ?)",
        ["sku-legacy", "Legacy item", "https://example.com/products/sku-legacy"],
    )
    conn.execute(
        "INSERT INTO price_snapshots (product_id, ts, current_price) VALUES (?, ?, ?)",
        ["sku-legacy", datetime(2026, 4, 13, 0, 0), 10_000],
    )
    conn.close()

    store = GraphStore(str(db_path))
    columns = {
        str(row[1])
        for row in store.conn.execute("PRAGMA table_info('price_snapshots')").fetchall()
    }
    outlier_flag = store.conn.execute(
        "SELECT outlier_flag FROM price_snapshots WHERE product_id = ?",
        ["sku-legacy"],
    ).fetchone()

    assert {
        "discount_price",
        "coupon_value",
        "card_benefit",
        "shipping_fee",
        "effective_price",
        "stock_status",
        "option_signature",
        "outlier_flag",
    } <= columns
    assert outlier_flag == (False,)
    store.close()


@pytest.mark.unit
def test_graph_store_persists_price_contract_fields(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "price.duckdb"))
    item = RawItem(
        product_id="sku-1",
        title="Contract item",
        url="https://example.com/products/sku-1",
        source="unit",
        collected_at=datetime(2026, 4, 13, 0, 0, tzinfo=UTC),
        current_price=10_000,
        discount_price=9_000,
        coupon_value=500,
        card_benefit=1_000,
        shipping_fee=3_000,
        effective_price=10_500,
        category="electronics",
        platform="example",
        option_signature="default",
        stock_status="in_stock",
        outlier_flag=True,
    )

    store.save_raw_item(item)
    row = store.conn.execute(
        """
        SELECT
            discount_price, coupon_value, card_benefit, shipping_fee,
            effective_price, stock_status, option_signature, outlier_flag
        FROM price_snapshots
        WHERE product_id = ?
        """,
        [item.product_id],
    ).fetchone()
    store.close()

    assert row == (9_000, 500, 1_000, 3_000, 10_500, "in_stock", "default", True)


@pytest.mark.unit
def test_deal_matched_entities_derives_price_report_entities() -> None:
    matches = _deal_matched_entities(
        {
            "title": "삼성전자 비스포크 제트 AI Lite VS28D950AIB",
            "category": "electronics",
            "platform": "elevenst",
            "source": "enuri_main",
            "discount_rate": 0.65,
            "current_price": 690_560,
        }
    )

    assert matches["category:electronics"] == ["electronics"]
    assert matches["platform:elevenst"] == ["elevenst"]
    assert matches["source:enuri_main"] == ["enuri_main"]
    assert matches["brand:삼성전자"] == ["삼성전자"]
    assert matches["discount:50%+"] == ["50%+"]
    assert matches["price_band:200k_plus"] == ["200k_plus"]


@pytest.mark.unit
def test_generate_report_writes_matched_price_summary(tmp_path) -> None:
    db_path = tmp_path / "price.duckdb"
    report_dir = tmp_path / "reports"
    store = GraphStore(str(db_path))
    item = RawItem(
        product_id="sku-report",
        title="삼성전자 비스포크 제트 AI Lite VS28D950AIB",
        url="https://example.com/products/sku-report",
        source="enuri_main",
        collected_at=datetime(2026, 4, 13, 0, 0, tzinfo=UTC),
        current_price=690_560,
        avg_price=1_000_000,
        discount_rate=0.65,
        category="electronics",
        platform="elevenst",
    )
    store.save_raw_item(item)
    store.save_price_score(
        PriceScore(
            product_id=item.product_id,
            radar_score=0.91,
            discount_strength=0.8,
            timing_rarity=0.7,
            popularity=0.5,
            volatility=0.1,
            current_price=item.current_price or 0,
            avg_price=item.avg_price,
            saving_amount=309_440,
            explanation="강한 할인 신호",
        )
    )
    store.close()

    generate_report(
        {
            "database": {"path": str(db_path)},
            "reporting": {"max_items_per_report": 10, "output_path": str(report_dir)},
        },
        output_dir=str(report_dir),
        quality_report={
            "summary": {
                "sku_price_snapshot_events": 1,
                "purchase_benefit_snapshot_events": 1,
                "stock_status_transition_events": 0,
                "official_source_backlog_count": 1,
                "authority_gap_review_count": 1,
                "outlier_event_count": 1,
                "daily_review_item_count": 2,
            },
            "events": [
                {
                    "event_model": "sku_price_snapshot",
                    "source_id": "enuri_main",
                    "title": item.title,
                    "effective_price": 690_560,
                    "stock_status": "in_stock",
                }
            ],
            "daily_review_items": [
                {
                    "reason": ["authority_gap"],
                    "title": "No official brand/store source enabled",
                    "detail": "coupang_brand_store_candidates",
                },
                {
                    "reason": ["price_outlier"],
                    "product_id": item.product_id,
                    "title": item.title,
                    "price_event_key": "sku-price-snapshot:enuri-main:sku-report:default:2026-04-13",
                }
            ],
            "official_source_backlog": [
                {
                    "id": "coupang_brand_store_candidates",
                    "name": "Coupang brand/store official pages",
                    "representative_domains": ["coupang.com"],
                }
            ],
        },
    )

    summary_path = next(report_dir.glob("price_*_summary.json"))
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert payload["article_count"] == 1
    assert payload["source_count"] == 1
    assert payload["matched_count"] == 1
    assert payload["sources"] == {"enuri_main": 1}
    assert payload["ontology"]["repo"] == "PriceRadar"
    assert payload["ontology"]["ontology_version"] == "0.1.0"
    assert "price.sku_price_snapshot" in payload["ontology"]["event_model_ids"]
    html = next(report_dir.glob("price_*.html")).read_text(encoding="utf-8")
    assert "Price Quality" in html
    assert "sku_price_snapshot" in html
    assert "price_outlier" in html
    assert "Coupang brand/store official pages" in html
    assert any(item["name"] == "brand:삼성전자" for item in payload["top_entities"])
