from __future__ import annotations

from datetime import datetime
from typing import Any

from dateutil import parser as date_parser

from .models import PriceEvent, PriceSnapshot, Product
from .scoring import compute_radar_score
from .storage import PriceStorage


def run_pipeline(
    raw_snapshots: list[dict[str, Any]], *, db_path, limit: int | None = None
) -> tuple[int, int, int]:
    """스냅샷 JSON 배열 → 정규화 → 스코어링 → DuckDB 저장."""
    normalized_products: dict[str, Product] = {}
    snapshots: list[PriceSnapshot] = []
    events: list[PriceEvent] = []

    for idx, item in enumerate(raw_snapshots):
        if limit is not None and idx >= limit:
            break
        snap, product = _normalize_snapshot(item)
        normalized_products[product.id] = product
        snapshots.append(snap)

        is_new_low = bool(item.get("is_new_low") or item.get("list_type") == "lowest_now")
        popularity_hint = float(item.get("popularity_hint", 0))
        volatility_hint = item.get("volatility")
        events.append(
            compute_radar_score(
                snapshot=snap,
                is_new_low=is_new_low,
                popularity_hint=popularity_hint,
                volatility_hint=volatility_hint,
            )
        )

    store = PriceStorage(db_path)
    store.upsert_products(normalized_products.values())
    n_snap = store.insert_snapshots(snapshots)
    n_events = store.insert_events(events)
    store.close()
    return len(normalized_products), n_snap, n_events


def _normalize_snapshot(item: dict[str, Any]) -> tuple[PriceSnapshot, Product]:
    """입력 JSON을 내부 스키마로 변환."""
    product_id = item.get("product_id") or "unknown"
    ts_raw = item.get("timestamp") or item.get("ts") or datetime.utcnow().isoformat()
    ts = date_parser.parse(ts_raw)

    product = Product(
        id=product_id,
        title=item.get("title", "unknown"),
        category=item.get("category", "misc"),
        brand=item.get("brand"),
        source_platform=item.get("source_platform", "unknown"),
        product_url=item.get("product_url", ""),
        image_url=item.get("image_url"),
        attributes=item.get("attributes") or {},
    )

    discount_vs_avg = item.get("discount_rate_vs_avg")
    if discount_vs_avg is None and item.get("avg_price_30d"):
        avg = float(item["avg_price_30d"])
        price = float(item.get("price", 0))
        discount_vs_avg = (avg - price) / avg if avg > 0 else None

    snapshot = PriceSnapshot(
        product_id=product_id,
        ts=ts,
        price=int(item.get("price", 0)),
        avg_price_30d=_safe_int(item.get("avg_price_30d")),
        avg_price_90d=_safe_int(item.get("avg_price_90d")),
        discount_rate_vs_avg=discount_vs_avg,
        discount_rate_vs_list=item.get("discount_rate_vs_list"),
        source=item.get("source", "fallcent"),
        meta={
            "list_type": item.get("list_type"),
            "is_hotdeal_listed": item.get("is_hotdeal_listed"),
        },
    )
    return snapshot, product


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
