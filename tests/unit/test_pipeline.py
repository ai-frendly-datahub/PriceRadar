from __future__ import annotations

import pytest

from priceradar.pipeline import _safe_int


@pytest.mark.unit
def test_safe_int_with_valid_int() -> None:
    """_safe_int should convert valid int to int."""
    result = _safe_int(100)
    assert result == 100


@pytest.mark.unit
def test_safe_int_with_valid_string() -> None:
    """_safe_int should convert valid string to int."""
    result = _safe_int("100")
    assert result == 100


@pytest.mark.unit
def test_safe_int_with_float() -> None:
    """_safe_int should convert float to int."""
    result = _safe_int(100.5)
    assert result == 100


@pytest.mark.unit
def test_safe_int_with_none() -> None:
    """_safe_int should return None for None input."""
    result = _safe_int(None)
    assert result is None


@pytest.mark.unit
def test_safe_int_with_invalid_string() -> None:
    """_safe_int should return None for invalid string."""
    result = _safe_int("not_a_number")
    assert result is None


@pytest.mark.unit
def test_safe_int_with_empty_string() -> None:
    """_safe_int should return None for empty string."""
    result = _safe_int("")
    assert result is None


@pytest.mark.unit
def test_safe_int_with_list() -> None:
    """_safe_int should return None for list input."""
    result = _safe_int([1, 2, 3])
    assert result is None


@pytest.mark.unit
def test_safe_int_with_dict() -> None:
    """_safe_int should return None for dict input."""
    result = _safe_int({"key": "value"})
    assert result is None


@pytest.mark.unit
def test_safe_int_with_zero() -> None:
    """_safe_int should handle zero correctly."""
    result = _safe_int(0)
    assert result == 0


@pytest.mark.unit
def test_safe_int_with_negative() -> None:
    """_safe_int should handle negative numbers."""
    result = _safe_int(-100)
    assert result == -100


@pytest.mark.unit
def test_safe_int_with_large_number() -> None:
    """_safe_int should handle large numbers."""
    result = _safe_int(1000000000)
    assert result == 1000000000


@pytest.mark.unit
def test_normalize_snapshot_with_minimal_data() -> None:
    """_normalize_snapshot handles minimal data."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    assert snap.product_id == "prod_001"
    assert product.id == "prod_001"
    assert product.title == "unknown"


@pytest.mark.unit
def test_normalize_snapshot_with_full_data() -> None:
    """_normalize_snapshot handles full data."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "title": "Test Product",
        "category": "Electronics",
        "brand": "TestBrand",
        "source_platform": "coupang",
        "product_url": "https://example.com/product",
        "image_url": "https://example.com/image.jpg",
        "price": 50000,
        "avg_price_30d": 60000,
        "avg_price_90d": 65000,
        "timestamp": "2024-01-01T00:00:00",
        "source": "fallcent",
    }
    
    snap, product = _normalize_snapshot(item)
    
    assert snap.product_id == "prod_001"
    assert product.title == "Test Product"
    assert snap.price == 50000
    assert snap.avg_price_30d == 60000


@pytest.mark.unit
def test_normalize_snapshot_calculates_discount_rate() -> None:
    """_normalize_snapshot calculates discount rate from prices."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "price": 50000,
        "avg_price_30d": 60000,
    }
    
    snap, product = _normalize_snapshot(item)
    
    # (60000 - 50000) / 60000 = 0.1667
    assert snap.discount_rate_vs_avg is not None
    assert abs(snap.discount_rate_vs_avg - 0.1667) < 0.001


@pytest.mark.unit
def test_normalize_snapshot_with_zero_avg_price() -> None:
    """_normalize_snapshot handles zero avg price."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "price": 50000,
        "avg_price_30d": 0,
    }
    
    snap, product = _normalize_snapshot(item)
    
    assert snap.discount_rate_vs_avg is None


@pytest.mark.unit
def test_normalize_snapshot_with_timestamp_parsing() -> None:
    """_normalize_snapshot parses various timestamp formats."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "timestamp": "2024-01-15T10:30:00",
    }
    
    snap, product = _normalize_snapshot(item)
    
    assert snap.ts.year == 2024
    assert snap.ts.month == 1
    assert snap.ts.day == 15


@pytest.mark.unit
def test_normalize_snapshot_with_ts_fallback() -> None:
    """_normalize_snapshot uses ts field as fallback."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "ts": "2024-02-20T15:45:00",
    }
    
    snap, product = _normalize_snapshot(item)
    
    assert snap.ts.month == 2
    assert snap.ts.day == 20


@pytest.mark.unit
def test_normalize_snapshot_with_attributes() -> None:
    """_normalize_snapshot preserves attributes."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "attributes": {"color": "red", "size": "L"},
    }
    
    snap, product = _normalize_snapshot(item)
    
    assert product.attributes == {"color": "red", "size": "L"}


@pytest.mark.unit
def test_normalize_snapshot_with_meta_fields() -> None:
    """_normalize_snapshot includes meta fields."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "list_type": "lowest_now",
        "is_hotdeal_listed": True,
    }
    
    snap, product = _normalize_snapshot(item)
    
    assert snap.meta["list_type"] == "lowest_now"
    assert snap.meta["is_hotdeal_listed"] is True


@pytest.mark.unit
def test_safe_int_with_string_number() -> None:
    """_safe_int converts string numbers."""
    result = _safe_int("12345")
    assert result == 12345


@pytest.mark.unit
def test_safe_int_with_float_string() -> None:
    """_safe_int returns None for float strings."""
    result = _safe_int("123.45")
    assert result is None


@pytest.mark.unit
def test_safe_int_with_whitespace() -> None:
    """_safe_int handles whitespace in strings."""
    result = _safe_int("  456  ")
    assert result == 456


@pytest.mark.unit
def test_safe_int_with_negative_string() -> None:
    """_safe_int handles negative string numbers."""
    result = _safe_int("-789")
    assert result == -789


# ============================================================================
# run_pipeline() tests - Full cycle and edge cases
# ============================================================================


@pytest.mark.unit
def test_run_pipeline_with_single_snapshot(tmp_path) -> None:
    """run_pipeline processes single snapshot correctly."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data = [
        {
            "product_id": "prod_001",
            "title": "Test Product",
            "price": 50000,
            "avg_price_30d": 60000,
            "source": "fallcent",
        }
    ]
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path)
    
    assert n_products == 1
    assert n_snapshots == 1
    assert n_events == 1


@pytest.mark.unit
def test_run_pipeline_with_multiple_snapshots(tmp_path) -> None:
    """run_pipeline handles multiple snapshots."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data = [
        {
            "product_id": "prod_001",
            "title": "Product 1",
            "price": 50000,
            "source": "fallcent",
        },
        {
            "product_id": "prod_002",
            "title": "Product 2",
            "price": 30000,
            "source": "enuri",
        },
        {
            "product_id": "prod_003",
            "title": "Product 3",
            "price": 70000,
            "source": "fallcent",
        },
    ]
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path)
    
    assert n_products == 3
    assert n_snapshots == 3
    assert n_events == 3


@pytest.mark.unit
def test_run_pipeline_with_duplicate_products(tmp_path) -> None:
    """run_pipeline deduplicates products by ID."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data = [
        {
            "product_id": "prod_001",
            "title": "Product 1",
            "price": 50000,
        },
        {
            "product_id": "prod_001",
            "title": "Product 1 Updated",
            "price": 45000,
        },
    ]
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path)
    
    # Only 1 unique product, but 2 snapshots
    assert n_products == 1
    assert n_snapshots == 2
    assert n_events == 2


@pytest.mark.unit
def test_run_pipeline_with_limit(tmp_path) -> None:
    """run_pipeline respects limit parameter."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data = [
        {"product_id": f"prod_{i:03d}", "price": 10000 + i * 1000}
        for i in range(10)
    ]
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path, limit=5)
    
    assert n_products == 5
    assert n_snapshots == 5
    assert n_events == 5


@pytest.mark.unit
def test_run_pipeline_with_empty_list(tmp_path) -> None:
    """run_pipeline handles empty snapshot list."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data: list = []
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path)
    
    assert n_products == 0
    assert n_snapshots == 0
    assert n_events == 0


@pytest.mark.unit
def test_run_pipeline_with_is_new_low_flag(tmp_path) -> None:
    """run_pipeline passes is_new_low to scoring."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data = [
        {
            "product_id": "prod_001",
            "price": 50000,
            "is_new_low": True,
        }
    ]
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path)
    
    assert n_events == 1


@pytest.mark.unit
def test_run_pipeline_with_lowest_now_list_type(tmp_path) -> None:
    """run_pipeline detects lowest_now from list_type."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data = [
        {
            "product_id": "prod_001",
            "price": 50000,
            "list_type": "lowest_now",
        }
    ]
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path)
    
    assert n_events == 1


@pytest.mark.unit
def test_run_pipeline_with_popularity_hint(tmp_path) -> None:
    """run_pipeline passes popularity_hint to scoring."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data = [
        {
            "product_id": "prod_001",
            "price": 50000,
            "popularity_hint": 0.85,
        }
    ]
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path)
    
    assert n_events == 1


@pytest.mark.unit
def test_run_pipeline_with_volatility_hint(tmp_path) -> None:
    """run_pipeline passes volatility_hint to scoring."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data = [
        {
            "product_id": "prod_001",
            "price": 50000,
            "volatility_hint": "high",
        }
    ]
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path)
    
    assert n_events == 1


@pytest.mark.unit
def test_run_pipeline_with_missing_popularity_hint(tmp_path) -> None:
    """run_pipeline defaults popularity_hint to 0."""
    from priceradar.pipeline import run_pipeline
    
    db_path = str(tmp_path / "test.db")
    raw_data = [
        {
            "product_id": "prod_001",
            "price": 50000,
        }
    ]
    
    n_products, n_snapshots, n_events = run_pipeline(raw_data, db_path=db_path)
    
    assert n_events == 1


@pytest.mark.unit
def test_normalize_snapshot_with_missing_product_id() -> None:
    """_normalize_snapshot defaults product_id to 'unknown'."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"title": "Test"}
    snap, product = _normalize_snapshot(item)
    
    assert snap.product_id == "unknown"
    assert product.id == "unknown"


@pytest.mark.unit
def test_normalize_snapshot_with_missing_timestamp() -> None:
    """_normalize_snapshot uses current time if timestamp missing."""
    from priceradar.pipeline import _normalize_snapshot
    from datetime import datetime
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    # Should have a timestamp close to now
    assert snap.ts is not None
    assert isinstance(snap.ts, datetime)


@pytest.mark.unit
def test_normalize_snapshot_with_missing_price() -> None:
    """_normalize_snapshot defaults price to 0."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    assert snap.price == 0


@pytest.mark.unit
def test_normalize_snapshot_with_missing_category() -> None:
    """_normalize_snapshot defaults category to 'misc'."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    assert product.category == "misc"


@pytest.mark.unit
def test_normalize_snapshot_with_missing_source() -> None:
    """_normalize_snapshot defaults source to 'fallcent'."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    assert snap.source == "fallcent"


@pytest.mark.unit
def test_normalize_snapshot_with_discount_rate_vs_list() -> None:
    """_normalize_snapshot preserves discount_rate_vs_list."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "discount_rate_vs_list": 0.15,
    }
    snap, product = _normalize_snapshot(item)
    
    assert snap.discount_rate_vs_list == 0.15


@pytest.mark.unit
def test_normalize_snapshot_with_explicit_discount_rate() -> None:
    """_normalize_snapshot uses explicit discount_rate_vs_avg."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "discount_rate_vs_avg": 0.25,
        "price": 50000,
        "avg_price_30d": 60000,
    }
    snap, product = _normalize_snapshot(item)
    
    # Explicit value should be used, not calculated
    assert snap.discount_rate_vs_avg == 0.25


@pytest.mark.unit
def test_normalize_snapshot_with_none_attributes() -> None:
    """_normalize_snapshot handles None attributes."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "attributes": None,
    }
    snap, product = _normalize_snapshot(item)
    
    assert product.attributes == {}


@pytest.mark.unit
def test_normalize_snapshot_with_missing_brand() -> None:
    """_normalize_snapshot allows None brand."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    assert product.brand is None


@pytest.mark.unit
def test_normalize_snapshot_with_missing_image_url() -> None:
    """_normalize_snapshot allows None image_url."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    assert product.image_url is None


@pytest.mark.unit
def test_normalize_snapshot_with_missing_product_url() -> None:
    """_normalize_snapshot defaults product_url to empty string."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    assert product.product_url == ""


@pytest.mark.unit
def test_normalize_snapshot_with_missing_source_platform() -> None:
    """_normalize_snapshot defaults source_platform to 'unknown'."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    assert product.source_platform == "unknown"


@pytest.mark.unit
def test_normalize_snapshot_meta_with_none_values() -> None:
    """_normalize_snapshot includes None values in meta."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {"product_id": "prod_001"}
    snap, product = _normalize_snapshot(item)
    
    assert snap.meta["list_type"] is None
    assert snap.meta["is_hotdeal_listed"] is None


@pytest.mark.unit
def test_normalize_snapshot_with_string_price() -> None:
    """_normalize_snapshot converts string price to int."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "price": "50000",
    }
    snap, product = _normalize_snapshot(item)
    
    assert snap.price == 50000
    assert isinstance(snap.price, int)


@pytest.mark.unit
def test_normalize_snapshot_with_float_price() -> None:
    """_normalize_snapshot converts float price to int."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "price": 50000.99,
    }
    snap, product = _normalize_snapshot(item)
    
    assert snap.price == 50000


@pytest.mark.unit
def test_normalize_snapshot_discount_calculation_precision() -> None:
    """_normalize_snapshot calculates discount rate with precision."""
    from priceradar.pipeline import _normalize_snapshot
    
    item = {
        "product_id": "prod_001",
        "price": 33333,
        "avg_price_30d": 50000,
    }
    snap, product = _normalize_snapshot(item)
    
    # (50000 - 33333) / 50000 = 0.33334
    assert snap.discount_rate_vs_avg is not None
    assert abs(snap.discount_rate_vs_avg - 0.33334) < 0.00001
