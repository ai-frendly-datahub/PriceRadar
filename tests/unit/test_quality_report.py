from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from priceradar.quality_report import build_quality_report, write_quality_report


@pytest.mark.unit
def test_build_quality_report_tracks_contract_coverage() -> None:
    config = {
        "data_quality": {
            "priority": "P1",
            "primary_motion": "conversion",
            "source_contracts": {
                "default": {
                    "canonical_key_fields": ["source_id", "platform", "product_id"],
                    "effective_price_fields": ["list_price", "effective_price", "shipping_fee"],
                    "stock_fields": ["stock_status"],
                    "event_models": ["sku_price_snapshot", "stock_status_transition"],
                    "verification_role": "market_price_reference",
                },
                "overrides": {
                    "deal_feed": {
                        "event_models": ["deal_listing"],
                        "verification_role": "community_deal_reference",
                    }
                },
            },
            "official_source_backlog": [
                {"id": "official_store", "representative_domains": ["store.example.com"]}
            ],
            "next_actions": ["activate official sources after ToS review"],
        },
        "sources": [
            {"id": "price_tracker", "name": "Price Tracker", "type": "fallcent", "enabled": True},
            {"id": "deal_feed", "name": "Deal Feed", "type": "algumon", "enabled": True},
            {"id": "disabled_feed", "name": "Disabled Feed", "type": "browser", "enabled": False},
        ],
    }

    report = build_quality_report(
        config,
        generated_at=datetime(2026, 4, 12, tzinfo=UTC),
        target_date=date(2026, 4, 12),
    )

    assert report["repo"] == "PriceRadar"
    assert report["target_date"] == "2026-04-12"
    assert report["summary"]["enabled_source_count"] == 2
    assert report["summary"]["configured_source_count"] == 3
    assert report["summary"]["canonical_key_coverage"] == 1.0
    assert report["summary"]["effective_price_coverage"] == 1.0
    assert report["summary"]["stock_signal_coverage"] == 1.0
    assert report["summary"]["verification_signal_coverage"] == 1.0
    assert report["summary"]["official_source_backlog_count"] == 1
    assert report["summary"]["official_candidate_domain_count"] == 1
    assert report["summary"]["authority_gap_review_count"] == 1
    assert report["summary"]["missing_required_components"] == []
    assert report["source_status"][1]["event_models"] == ["deal_listing"]
    assert report["daily_review_items"][0]["reason"] == ["authority_gap"]


@pytest.mark.unit
def test_build_quality_report_tracks_price_event_rows_and_review_items() -> None:
    config = {
        "data_quality": {
            "source_contracts": {
                "default": {
                    "canonical_key_fields": ["source_id", "platform", "product_id"],
                    "effective_price_fields": ["discount_price", "effective_price"],
                    "stock_fields": ["stock_status"],
                    "event_models": [
                        "sku_price_snapshot",
                        "purchase_benefit_snapshot",
                        "stock_status_transition",
                    ],
                    "verification_role": "market_price_reference",
                }
            },
            "official_source_backlog": [
                {"id": "official_store", "representative_domains": ["store.example.com"]}
            ],
        },
        "sources": [
            {
                "id": "price_tracker",
                "name": "Price Tracker",
                "type": "fallcent",
                "enabled": True,
                "trust_tier": "T2_expert",
            }
        ],
    }
    deal_rows = [
        {
            "product_id": "sku-1",
            "title": "Contract item",
            "url": "https://example.com/products/sku-1",
            "source": "price_tracker",
            "platform": "example",
            "category": "electronics",
            "brand": "Example",
            "collected_at": datetime(2026, 4, 12, 9, 0, tzinfo=UTC),
            "current_price": 10_000,
            "discount_price": 9_000,
            "coupon_value": 500,
            "card_benefit": 1_000,
            "shipping_fee": 3_000,
            "effective_price": 10_500,
            "discount_rate": 0.55,
            "stock_status": "in_stock",
            "option_signature": "default",
            "outlier_flag": True,
            "radar_score": 0.91,
        }
    ]

    report = build_quality_report(
        config,
        generated_at=datetime(2026, 4, 12, tzinfo=UTC),
        target_date=date(2026, 4, 12),
        deal_rows=deal_rows,
    )

    assert report["summary"]["tracked_price_event_count"] == 3
    assert report["summary"]["sku_price_snapshot_events"] == 1
    assert report["summary"]["purchase_benefit_snapshot_events"] == 1
    assert report["summary"]["stock_status_transition_events"] == 1
    assert report["summary"]["effective_price_present_count"] == 1
    assert report["summary"]["purchase_benefit_present_count"] == 1
    assert report["summary"]["stock_status_present_count"] == 1
    assert report["summary"]["outlier_event_count"] == 1
    assert report["summary"]["daily_review_item_count"] == 2
    assert report["summary"]["authority_gap_review_count"] == 1
    event = report["events"][0]
    assert event["price_event_key"] == "sku-price-snapshot:price-tracker:sku-1:default:2026-04-12"
    assert event["effective_price"] == 10_500
    assert event["verification_role"] == "market_price_reference"
    assert report["daily_review_items"][0]["reason"] == ["authority_gap"]
    assert report["daily_review_items"][1]["reason"] == [
        "price_outlier",
        "high_discount_review",
    ]


@pytest.mark.unit
def test_write_quality_report_writes_latest_and_dated_paths(tmp_path) -> None:
    report = {
        "target_date": "2026-04-12",
        "summary": {},
    }

    paths = write_quality_report(report, tmp_path, target_date=date(2026, 4, 12))

    assert sorted(paths) == ["dated", "latest"]
    assert (tmp_path / "price_quality.json").exists()
    assert (tmp_path / "price_20260412_quality.json").exists()
