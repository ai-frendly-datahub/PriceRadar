from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import PriceEvent, PriceSnapshot


@dataclass
class ScoreConfig:
    w_discount: float = 0.4
    w_timing: float = 0.3
    w_popularity: float = 0.2
    w_stability: float = 0.1  # stability = 1 - volatility


def compute_radar_score(
    snapshot: PriceSnapshot,
    *,
    is_new_low: bool,
    popularity_hint: float = 0.0,
    volatility_hint: Optional[float] = None,
    config: Optional[ScoreConfig] = None,
) -> PriceEvent:
    cfg = config or ScoreConfig()

    discount_strength = _clamp01(snapshot.discount_rate_vs_avg or 0.0)
    timing_rarity = 1.0 if is_new_low else 0.5
    popularity = _clamp01(popularity_hint)
    volatility = _clamp01(volatility_hint) if volatility_hint is not None else 0.0
    stability = 1 - volatility

    radar_score = (
        cfg.w_discount * discount_strength
        + cfg.w_timing * timing_rarity
        + cfg.w_popularity * popularity
        + cfg.w_stability * stability
    )

    event_type = "NEW_LOW" if is_new_low else "BIG_DROP" if discount_strength >= 0.2 else "POPULAR_SPIKE"
    explanation = _build_explanation(snapshot, discount_strength, timing_rarity, popularity, volatility)
    saving_vs_avg = None
    if snapshot.avg_price_30d and snapshot.price:
        saving_vs_avg = max(snapshot.avg_price_30d - snapshot.price, 0)

    drop_rate = None
    if snapshot.discount_rate_vs_avg is not None:
        drop_rate = snapshot.discount_rate_vs_avg

    return PriceEvent(
        product_id=snapshot.product_id,
        event_ts=snapshot.ts,
        event_type=event_type,
        drop_rate=drop_rate,
        saving_vs_avg=saving_vs_avg,
        radar_score=round(radar_score, 4),
        explanation=explanation,
    )


def _build_explanation(snapshot: PriceSnapshot, discount_strength: float, timing: float, popularity: float, volatility: float) -> str:
    parts = []
    if snapshot.avg_price_30d:
        diff = snapshot.avg_price_30d - snapshot.price
        if diff > 0:
            parts.append(f"평균 대비 약 {diff:,}원 저렴")
    if discount_strength >= 0.3:
        parts.append("할인 강도 높음")
    if timing >= 0.9:
        parts.append("최근 최저가 구간")
    if popularity >= 0.6:
        parts.append("인기도 신호 있음")
    if volatility >= 0.5:
        parts.append("가격 변동성 주의")
    if not parts:
        return "가격 변동을 모니터링 중"
    return ", ".join(parts)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
