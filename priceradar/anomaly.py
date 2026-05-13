"""Price spike / cliff anomaly detection.

Each product accumulates a small price history (``data/priceradar.duckdb``
already stores ``price_snapshots``). This module flags two kinds of
anomalies given a per-product timeline:

- ``spike``: current price is unusually HIGH vs the recent baseline
  (rare for retail, but catches markup-then-pretend-discount tactics).
- ``cliff``: current price is unusually LOW (genuine deal signal).

The detector uses a 14-day rolling window:
- requires at least ``min_observations`` (default 5) data points
- computes mean + stdev of the window
- z = (current - mean) / stdev
- a ``cliff`` fires when z <= -threshold, ``spike`` when z >= +threshold
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean, stdev


@dataclass(frozen=True)
class PricePoint:
    timestamp: datetime
    price: float


@dataclass(frozen=True)
class PriceAnomaly:
    product_id: str
    timestamp: datetime
    price: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    kind: str  # "spike" | "cliff"


def _coerce_dt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def detect_anomalies(
    product_id: str,
    points: Sequence[PricePoint],
    *,
    window_days: int = 14,
    min_observations: int = 5,
    z_threshold: float = 2.0,
) -> list[PriceAnomaly]:
    """Scan a per-product price timeline and emit one anomaly per qualifying
    observation. Points are processed in their original order; for each
    point the baseline is the strictly-preceding window.
    """
    if len(points) < min_observations + 1:
        return []

    anomalies: list[PriceAnomaly] = []
    cleaned = [PricePoint(_coerce_dt(p.timestamp), float(p.price)) for p in points]
    cleaned.sort(key=lambda p: p.timestamp)

    for i in range(min_observations, len(cleaned)):
        current = cleaned[i]
        window_start = current.timestamp - timedelta(days=window_days)
        window = [p for p in cleaned[:i] if p.timestamp >= window_start]
        if len(window) < min_observations:
            continue
        prices = [p.price for p in window]
        baseline = mean(prices)
        sigma = stdev(prices) if len(prices) > 1 else 0.0
        if sigma == 0:
            # Constant baseline: fall back to relative-change detection.
            if baseline == 0:
                continue
            pct = (current.price - baseline) / baseline
            # ±10% relative-change threshold for constant baselines.
            if pct >= 0.10:
                kind = "spike"
                z = pct * z_threshold / 0.10  # display z-equivalent
            elif pct <= -0.10:
                kind = "cliff"
                z = pct * z_threshold / 0.10
            else:
                continue
            sigma = 0.0
        else:
            z = (current.price - baseline) / sigma
            if z >= z_threshold:
                kind = "spike"
            elif z <= -z_threshold:
                kind = "cliff"
            else:
                continue
        anomalies.append(
            PriceAnomaly(
                product_id=product_id,
                timestamp=current.timestamp,
                price=current.price,
                baseline_mean=round(baseline, 2),
                baseline_std=round(sigma, 2),
                z_score=round(z, 2),
                kind=kind,
            )
        )
    return anomalies


def detect_for_products(
    histories: Iterable[tuple[str, Sequence[PricePoint]]],
    **kwargs: object,
) -> list[PriceAnomaly]:
    """Apply ``detect_anomalies`` to many products at once."""
    out: list[PriceAnomaly] = []
    for product_id, points in histories:
        out.extend(detect_anomalies(product_id, points, **kwargs))  # type: ignore[arg-type]
    return out


__all__ = ["PricePoint", "PriceAnomaly", "detect_anomalies", "detect_for_products"]
