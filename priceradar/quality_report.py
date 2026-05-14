from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


DEFAULT_REPORT_NAME = "price_quality.json"
TRACKED_EVENT_MODEL_ORDER = [
    "sku_price_snapshot",
    "purchase_benefit_snapshot",
    "stock_status_transition",
]
TRACKED_EVENT_MODELS = set(TRACKED_EVENT_MODEL_ORDER)
BENEFIT_FIELDS = ["coupon_value", "card_benefit", "shipping_fee", "effective_price"]


def load_sources_config(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def build_quality_report(
    sources_config: dict[str, Any],
    *,
    generated_at: datetime | None = None,
    target_date: date | None = None,
    deal_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    target_date = target_date or generated_at.date()
    data_quality = _dict_value(sources_config.get("data_quality"))
    sources = [
        source
        for source in sources_config.get("sources", [])
        if isinstance(source, dict)
    ]
    source_contracts = _dict_value(data_quality.get("source_contracts"))
    default_contract = _dict_value(source_contracts.get("default"))
    source_overrides = _dict_value(source_contracts.get("overrides"))

    source_status = [
        _source_status(source, default_contract, _dict_value(source_overrides.get(str(source.get("id")))))
        for source in sources
    ]
    enabled_status = [row for row in source_status if row["enabled"]]
    official_backlog = list(data_quality.get("official_source_backlog") or [])
    quality_gates = _quality_gates(data_quality, enabled_status, official_backlog)
    tracked_event_models = _tracked_event_models(data_quality)
    deal_rows_list = list(deal_rows or [])
    events = _build_event_rows(
        deal_rows=deal_rows_list,
        source_status=source_status,
        tracked_event_models=tracked_event_models,
    )
    event_counts = _count_events(events)
    daily_review_items = _daily_review_items(events, enabled_status, official_backlog)
    current_price_null_by_source = _count_current_price_nulls(deal_rows_list)

    summary = {
        "priority": data_quality.get("priority", "P1"),
        "primary_motion": data_quality.get("primary_motion", "conversion"),
        "configured_source_count": len(source_status),
        "enabled_source_count": len(enabled_status),
        "canonical_key_coverage": _coverage(enabled_status, "has_canonical_key"),
        "effective_price_coverage": _coverage(enabled_status, "has_effective_price_fields"),
        "stock_signal_coverage": _coverage(enabled_status, "has_stock_signal"),
        "verification_signal_coverage": _coverage(enabled_status, "has_verification_role"),
        "official_source_backlog_count": len(official_backlog),
        "official_candidate_domain_count": sum(
            len(_list_value(item.get("representative_domains")))
            for item in official_backlog
            if isinstance(item, Mapping)
        ),
        "tracked_price_event_count": len(events),
        "daily_review_item_count": len(daily_review_items),
        "authority_gap_review_count": sum(
            1 for item in daily_review_items if item.get("reason") == ["authority_gap"]
        ),
        "unique_sku_count": len(
            {
                str(event.get("product_id") or "")
                for event in events
                if str(event.get("product_id") or "")
            }
        ),
        "effective_price_present_count": sum(
            1
            for event in events
            if event.get("event_model") == "sku_price_snapshot"
            and event.get("effective_price") is not None
        ),
        "purchase_benefit_present_count": event_counts.get("purchase_benefit_snapshot", 0),
        "stock_status_present_count": sum(
            1
            for event in events
            if event.get("event_model") == "stock_status_transition"
            and str(event.get("stock_status") or "")
        ),
        "outlier_event_count": sum(
            1
            for event in events
            if event.get("event_model") == "sku_price_snapshot" and event.get("outlier_flag")
        ),
        "current_price_null_total": sum(
            stats["null"] for stats in current_price_null_by_source.values()
        ),
        "current_price_null_by_source": current_price_null_by_source,
        "missing_required_components": [
            gate["name"] for gate in quality_gates if gate["status"] == "attention"
        ],
    }
    for event_model in TRACKED_EVENT_MODEL_ORDER:
        summary[f"{event_model}_events"] = event_counts.get(event_model, 0)

    return {
        "generated_at": generated_at.isoformat(),
        "target_date": target_date.isoformat(),
        "repo": "PriceRadar",
        "summary": summary,
        "required_components": data_quality.get("required_components", {}),
        "tracked_event_models": sorted(tracked_event_models),
        "quality_gates": quality_gates,
        "source_status": source_status,
        "events": events,
        "daily_review_items": daily_review_items,
        "official_source_backlog": official_backlog,
        "recommendations": _recommendations(summary, data_quality),
    }


def write_quality_report(
    report: dict[str, Any],
    output_dir: Path,
    *,
    target_date: date | None = None,
) -> dict[str, str]:
    target_date = target_date or date.fromisoformat(str(report["target_date"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = output_dir / DEFAULT_REPORT_NAME
    dated_path = output_dir / f"price_{target_date.strftime('%Y%m%d')}_quality.json"
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    latest_path.write_text(content, encoding="utf-8")
    dated_path.write_text(content, encoding="utf-8")
    return {"latest": str(latest_path), "dated": str(dated_path)}


def _source_status(
    source: dict[str, Any], default_contract: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    contract = _merge_contract(default_contract, override)
    event_models = _list_value(contract.get("event_models"))
    effective_price_fields = _list_value(contract.get("effective_price_fields"))
    canonical_key_fields = _list_value(contract.get("canonical_key_fields"))
    stock_fields = _list_value(contract.get("stock_fields"))
    verification_role = str(contract.get("verification_role") or "")

    return {
        "id": str(source.get("id") or source.get("name") or "unknown"),
        "name": str(source.get("name") or source.get("id") or "unknown"),
        "type": str(source.get("type") or "unknown"),
        "enabled": source.get("enabled", True) is not False,
        "trust_tier": source.get("trust_tier"),
        "category": source.get("category"),
        "event_models": event_models,
        "canonical_key_fields": canonical_key_fields,
        "effective_price_fields": effective_price_fields,
        "stock_fields": stock_fields,
        "verification_role": verification_role or None,
        "has_canonical_key": bool(canonical_key_fields),
        "has_effective_price_fields": bool(effective_price_fields),
        "has_stock_signal": bool(stock_fields)
        or any("stock" in str(model).lower() for model in event_models),
        "has_verification_role": bool(verification_role),
    }


def _build_event_rows(
    *,
    deal_rows: Iterable[Mapping[str, Any]],
    source_status: list[dict[str, Any]],
    tracked_event_models: set[str],
) -> list[dict[str, Any]]:
    sources_by_id = {row["id"]: row for row in source_status}
    events: list[dict[str, Any]] = []
    for deal in deal_rows:
        source_id = str(deal.get("source") or deal.get("platform") or "unknown")
        source = sources_by_id.get(source_id, {})
        if not source or source.get("enabled") is False:
            continue
        source_event_models = _event_models_for_source(source, tracked_event_models)
        if "sku_price_snapshot" in source_event_models and (
            _as_int(deal.get("current_price")) is not None
            or _as_int(deal.get("effective_price")) is not None
        ):
            events.append(_event_row(deal, source, "sku_price_snapshot"))
        if "purchase_benefit_snapshot" in source_event_models and _has_purchase_benefit(deal):
            events.append(_event_row(deal, source, "purchase_benefit_snapshot"))
        if "stock_status_transition" in source_event_models and str(
            deal.get("stock_status") or ""
        ).strip():
            events.append(_event_row(deal, source, "stock_status_transition"))
    return events


def _count_current_price_nulls(
    deal_rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    """Per-source counts of deals missing ``current_price``.

    Returned shape: ``{source_id: {"total": N, "null": K, "null_pct": float}}``.
    Sources that never appear in the deal stream are omitted.
    """
    counts: dict[str, dict[str, int]] = {}
    for deal in deal_rows:
        source_id = str(deal.get("source") or deal.get("platform") or "unknown")
        bucket = counts.setdefault(source_id, {"total": 0, "null": 0})
        bucket["total"] += 1
        if _as_int(deal.get("current_price")) is None:
            bucket["null"] += 1
    for bucket in counts.values():
        total = max(bucket["total"], 1)
        bucket["null_pct"] = round(100.0 * bucket["null"] / total, 2)
    return counts


def _event_models_for_source(
    source: dict[str, Any],
    tracked_event_models: set[str],
) -> set[str]:
    models = {
        str(model).strip()
        for model in _list_value(source.get("event_models"))
        if str(model).strip()
    }
    return models & tracked_event_models


def _event_row(
    deal: Mapping[str, Any],
    source: dict[str, Any],
    event_model: str,
) -> dict[str, Any]:
    current_price = _as_int(deal.get("current_price"))
    discount_price = _as_int(deal.get("discount_price"))
    effective_price = _as_int(deal.get("effective_price"))
    coupon_value = _as_int(deal.get("coupon_value"))
    card_benefit = _as_int(deal.get("card_benefit"))
    shipping_fee = _as_int(deal.get("shipping_fee"))
    product_id = str(deal.get("product_id") or "")
    option_signature = str(deal.get("option_signature") or "default")
    observed_at = _iso_datetime(deal.get("collected_at"))
    source_id = str(deal.get("source") or deal.get("platform") or source.get("id") or "unknown")
    row = {
        "event_model": event_model,
        "price_event_key": _price_event_key(
            event_model=event_model,
            source_id=source_id,
            product_id=product_id,
            option_signature=option_signature,
            observed_at=observed_at,
        ),
        "source_id": source_id,
        "source_name": source.get("name") or source_id,
        "verification_role": source.get("verification_role"),
        "trust_tier": source.get("trust_tier"),
        "product_id": product_id,
        "title": str(deal.get("title") or ""),
        "url": str(deal.get("url") or ""),
        "platform": str(deal.get("platform") or ""),
        "category": str(deal.get("category") or ""),
        "brand": str(deal.get("brand") or ""),
        "observed_at": observed_at,
        "current_price": current_price,
        "avg_price": _as_int(deal.get("avg_price")),
        "list_price": _as_int(deal.get("list_price")),
        "discount_price": discount_price,
        "coupon_value": coupon_value,
        "card_benefit": card_benefit,
        "shipping_fee": shipping_fee,
        "effective_price": effective_price,
        "discount_rate": _as_float(deal.get("discount_rate")),
        "radar_score": _as_float(deal.get("radar_score")),
        "stock_status": str(deal.get("stock_status") or ""),
        "option_signature": option_signature,
        "outlier_flag": bool(deal.get("outlier_flag")),
        "has_purchase_benefit": _has_purchase_benefit(deal),
    }
    if row["effective_price"] is None and discount_price is not None:
        row["effective_price"] = max(
            0,
            discount_price
            - (coupon_value or 0)
            - (card_benefit or 0)
            + (shipping_fee or 0),
        )
    if row["discount_price"] is None:
        row["discount_price"] = current_price
    return row


def _has_purchase_benefit(deal: Mapping[str, Any]) -> bool:
    if any(_as_int(deal.get(field)) not in (None, 0) for field in ("coupon_value", "card_benefit", "shipping_fee")):
        return True
    effective_price = _as_int(deal.get("effective_price"))
    base_price = _as_int(deal.get("discount_price")) or _as_int(deal.get("current_price"))
    return effective_price is not None and base_price is not None and effective_price != base_price


def _daily_review_items(
    events: list[dict[str, Any]],
    enabled_status: list[dict[str, Any]],
    official_backlog: list[Any],
) -> list[dict[str, Any]]:
    review_items = _event_review_items(events)
    if official_backlog and not any(_is_authoritative_source(row) for row in enabled_status):
        pending_ids = [
            str(item.get("id") or item.get("name") or "")
            for item in official_backlog
            if isinstance(item, Mapping)
        ]
        review_items.insert(
            0,
            {
                "reason": ["authority_gap"],
                "title": "No official brand/store source enabled",
                "detail": ", ".join(item for item in pending_ids if item),
            },
        )
    return review_items


def _event_review_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    review_items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for event in events:
        if event.get("event_model") != "sku_price_snapshot":
            continue
        reasons: list[str] = []
        if event.get("outlier_flag"):
            reasons.append("price_outlier")
        if event.get("event_model") == "sku_price_snapshot" and event.get(
            "effective_price"
        ) is None:
            reasons.append("missing_effective_price")
        if event.get("event_model") == "sku_price_snapshot" and not event.get("stock_status"):
            reasons.append("missing_stock_status")
        discount_rate = event.get("discount_rate")
        if isinstance(discount_rate, (int, float)) and discount_rate >= 0.5:
            reasons.append("high_discount_review")
        if not reasons:
            continue

        key = str(event.get("price_event_key") or "")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        review_items.append(
            {
                "reason": reasons,
                "source_id": event.get("source_id"),
                "product_id": event.get("product_id"),
                "title": event.get("title"),
                "url": event.get("url"),
                "current_price": event.get("current_price"),
                "effective_price": event.get("effective_price"),
                "stock_status": event.get("stock_status"),
                "outlier_flag": event.get("outlier_flag"),
                "radar_score": event.get("radar_score"),
                "price_event_key": key,
            }
        )
        if len(review_items) >= 10:
            break
    return review_items


def _is_authoritative_source(row: Mapping[str, Any]) -> bool:
    trust_tier = str(row.get("trust_tier") or "").lower()
    return trust_tier.startswith("t1")


def _count_events(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        model = str(event.get("event_model") or "")
        counts[model] = counts.get(model, 0) + 1
    return counts


def _quality_gates(
    data_quality: dict[str, Any],
    enabled_status: list[dict[str, Any]],
    official_backlog: list[Any],
) -> list[dict[str, str]]:
    gates = [
        (
            "canonical_sku_key",
            "enabled sources define canonical SKU key fields",
            bool(enabled_status) and all(row["has_canonical_key"] for row in enabled_status),
        ),
        (
            "effective_price_components",
            "enabled sources preserve list/discount/coupon/card/shipping/effective price fields",
            bool(enabled_status) and all(row["has_effective_price_fields"] for row in enabled_status),
        ),
        (
            "stock_status_transition",
            "at least one enabled source contract tracks stock or stockout transitions",
            any(row["has_stock_signal"] for row in enabled_status),
        ),
        (
            "verification_roles",
            "enabled sources are tagged with verification roles",
            bool(enabled_status) and all(row["has_verification_role"] for row in enabled_status),
        ),
        (
            "official_source_backlog",
            "official brand/store candidates are tracked separately before activation",
            bool(official_backlog),
        ),
    ]
    configured_gates = _list_value(data_quality.get("quality_gates"))
    results = [
        {
            "name": name,
            "status": "ok" if passed else "attention",
            "description": description,
        }
        for name, description, passed in gates
    ]
    for gate in configured_gates:
        if isinstance(gate, str):
            results.append({"name": gate, "status": "documented", "description": gate})
    return results


def _recommendations(summary: dict[str, Any], data_quality: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    if summary["effective_price_coverage"] < 1.0:
        recommendations.append("쿠폰·카드혜택·배송비 필드를 source contract에 추가한다.")
    if summary["stock_signal_coverage"] <= 0.0:
        recommendations.append("품절·재입고 전환을 별도 이벤트 모델로 수집한다.")
    if summary["official_source_backlog_count"] > 0:
        recommendations.append("공식 브랜드/스토어 후보는 ToS와 파싱 안정성 검증 후 단계적으로 활성화한다.")
    recommendations.extend(str(item) for item in _list_value(data_quality.get("next_actions")))
    return list(dict.fromkeys(recommendations))


def _tracked_event_models(data_quality: dict[str, Any]) -> set[str]:
    quality_outputs = _dict_value(data_quality.get("quality_outputs"))
    configured = {
        str(item).strip()
        for item in _list_value(quality_outputs.get("tracked_event_models"))
        if str(item).strip()
    }
    if configured:
        return configured & TRACKED_EVENT_MODELS or set(TRACKED_EVENT_MODELS)
    required = _dict_value(data_quality.get("required_components"))
    required_models = {
        str(item).strip()
        for item in _list_value(required.get("event_models"))
        if str(item).strip()
    }
    return required_models & TRACKED_EVENT_MODELS or set(TRACKED_EVENT_MODELS)


def _price_event_key(
    *,
    event_model: str,
    source_id: str,
    product_id: str,
    option_signature: str,
    observed_at: str,
) -> str:
    parts = [event_model, source_id, product_id, option_signature, observed_at[:10]]
    return ":".join(_normalize_key_text(part) for part in parts if str(part).strip())


def _normalize_key_text(value: Any) -> str:
    text = str(value).strip().lower()
    normalized = "".join(char if char.isalnum() else "-" for char in text)
    return "-".join(part for part in normalized.split("-") if part)


def _iso_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC).isoformat()
        return value.astimezone(UTC).isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if cleaned:
            try:
                return int(float(cleaned))
            except ValueError:
                return None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _merge_contract(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _coverage(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key)) / len(rows), 3)


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate PriceRadar data quality report")
    parser.add_argument("--sources", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--date", dest="target_date", default=None, help="YYYY-MM-DD")
    args = parser.parse_args(argv)

    target_date = date.fromisoformat(args.target_date) if args.target_date else None
    config = load_sources_config(args.sources)
    report = build_quality_report(config, target_date=target_date)
    paths = write_quality_report(report, args.output_dir, target_date=target_date)
    print(json.dumps(paths, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
