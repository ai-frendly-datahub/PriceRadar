from __future__ import annotations

from datetime import UTC, datetime, timedelta

from priceradar.anomaly import (
    PricePoint,
    detect_anomalies,
    detect_for_products,
)


def _steady_then(prices: list[float]) -> list[PricePoint]:
    base = datetime(2026, 4, 1, tzinfo=UTC)
    return [PricePoint(base + timedelta(days=i), float(p)) for i, p in enumerate(prices)]


def test_detect_cliff_when_price_drops() -> None:
    # 14-day flat baseline followed by a sharp cut.
    points = _steady_then([1000.0] * 14 + [600.0])
    anomalies = detect_anomalies("sku-cliff", points, z_threshold=2.0)
    assert len(anomalies) == 1
    assert anomalies[0].kind == "cliff"
    assert anomalies[0].price == 600.0


def test_detect_spike_when_price_jumps() -> None:
    points = _steady_then([1000.0] * 14 + [1500.0])
    # stdev of constant series is 0 → no anomaly. Add small noise.
    noisy = list(points)
    noisy[3] = PricePoint(noisy[3].timestamp, 1010.0)
    anomalies = detect_anomalies("sku-spike", noisy, z_threshold=2.0)
    assert any(a.kind == "spike" for a in anomalies)


def test_too_few_observations_returns_empty() -> None:
    points = _steady_then([100.0, 110.0, 120.0])  # only 3 points
    assert detect_anomalies("short", points) == []


def test_constant_baseline_falls_back_to_relative_change() -> None:
    # stdev is 0 → falls back to ±10% relative-change check.
    points = _steady_then([100.0] * 10)
    points.append(PricePoint(points[-1].timestamp + timedelta(days=1), 500.0))
    anomalies = detect_anomalies("flat", points, z_threshold=2.0)
    # 500 vs 100 is +400% → spike.
    assert len(anomalies) == 1
    assert anomalies[0].kind == "spike"


def test_constant_baseline_small_change_skipped() -> None:
    points = _steady_then([100.0] * 10)
    points.append(PricePoint(points[-1].timestamp + timedelta(days=1), 105.0))
    # +5% < 10% threshold → no anomaly.
    anomalies = detect_anomalies("flat", points, z_threshold=2.0)
    assert anomalies == []


def test_detect_for_products_runs_per_product() -> None:
    flat = _steady_then([100.0] * 14 + [50.0])
    other = _steady_then([20.0] * 14 + [10.0])
    anomalies = detect_for_products(
        [("p1", flat), ("p2", other)], z_threshold=2.0
    )
    assert {a.product_id for a in anomalies} == {"p1", "p2"}


def test_baseline_window_respected() -> None:
    # 30 days of slowly rising prices, plus an outlier far from the
    # most-recent 14 days — should NOT fire because the moving baseline
    # already drifted up.
    base = datetime(2026, 3, 1, tzinfo=UTC)
    points = [
        PricePoint(base + timedelta(days=i), 100.0 + i * 5.0) for i in range(30)
    ]
    final = points[-1].price
    points.append(PricePoint(points[-1].timestamp + timedelta(days=1), final + 5.0))
    anomalies = detect_anomalies("drift", points, z_threshold=2.0)
    # The trending series has a stdev so a continuation of the trend should
    # not be an anomaly.
    assert not any(a.timestamp == points[-1].timestamp for a in anomalies)
