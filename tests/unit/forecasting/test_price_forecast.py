from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from priceradar.forecasting import price_forecast
from priceradar.forecasting.price_forecast import forecast_category_prices
from priceradar.models import Deal


def _build_deals(category: str, days: int, base_price: float) -> list[Deal]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    deals: list[Deal] = []
    for day in range(days):
        deals.append(
            Deal(
                price=base_price + float(day * 1000),
                category=category,
                collected_at=start + timedelta(days=day),
            )
        )
    return deals


def _fake_forecast(value: float) -> dict[str, list[float]]:
    return {
        "forecast": [value + float(idx) for idx in range(14)],
        "lower_80": [value - 1000.0 + float(idx) for idx in range(14)],
        "upper_80": [value + 1000.0 + float(idx) for idx in range(14)],
        "lower_95": [value - 1500.0 + float(idx) for idx in range(14)],
        "upper_95": [value + 1500.0 + float(idx) for idx in range(14)],
    }


@pytest.mark.unit
def test_forecast_category_prices_returns_14_day_output(monkeypatch: pytest.MonkeyPatch) -> None:
    deals = _build_deals("Laptop", 30, 100000.0)
    deals.extend(_build_deals("Tablet", 22, 70000.0))

    def fake_arima(series: list[float]) -> dict[str, list[float]]:
        return _fake_forecast(series[-1])

    monkeypatch.setattr(price_forecast, "_try_arima_forecast", fake_arima)

    result = forecast_category_prices(deals, top_n=1)

    assert "Laptop" in result
    assert len(result["Laptop"]["dates"]) == 14
    assert len(result["Laptop"]["forecast"]) == 14
    assert len(result["Laptop"]["lower_80"]) == 14
    assert len(result["Laptop"]["upper_80"]) == 14
    assert len(result["Laptop"]["lower_95"]) == 14
    assert len(result["Laptop"]["upper_95"]) == 14


@pytest.mark.unit
def test_forecast_category_prices_skips_categories_with_short_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deals = _build_deals("Laptop", 30, 100000.0)
    deals.extend(_build_deals("Sparse", 20, 50000.0))

    def fake_arima(series: list[float]) -> dict[str, list[float]]:
        return _fake_forecast(series[-1])

    monkeypatch.setattr(price_forecast, "_try_arima_forecast", fake_arima)

    result = forecast_category_prices(deals, top_n=5)

    assert "Laptop" in result
    assert "Sparse" not in result


@pytest.mark.unit
def test_forecast_category_prices_uses_prophet_when_arima_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deals = _build_deals("Laptop", 30, 100000.0)
    call_flags = {"arima": False, "prophet": False}

    def fake_arima(series: list[float]) -> None:
        _ = series
        call_flags["arima"] = True
        return None

    def fake_prophet(series: list[float]) -> dict[str, list[float]]:
        call_flags["prophet"] = True
        return _fake_forecast(series[-1])

    monkeypatch.setattr(price_forecast, "_try_arima_forecast", fake_arima)
    monkeypatch.setattr(price_forecast, "_try_prophet_forecast", fake_prophet)

    result = forecast_category_prices(deals, top_n=1)

    assert call_flags["arima"] is True
    assert call_flags["prophet"] is True
    assert "Laptop" in result
