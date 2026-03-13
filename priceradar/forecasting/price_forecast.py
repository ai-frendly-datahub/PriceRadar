from __future__ import annotations

import importlib
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from priceradar.models import Deal


FORECAST_HORIZON_DAYS = 14
MIN_HISTORY_DAYS = 21
Z_SCORE_80 = 1.2815515655446004
Z_SCORE_95 = 1.959963984540054


def forecast_category_prices(deals: list[Deal], top_n: int = 5) -> dict[str, dict[str, list[Any]]]:
    if top_n <= 0:
        return {}

    category_daily_prices, category_counts = _aggregate_daily_average_prices(deals)
    ranked_categories = sorted(
        category_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )[:top_n]

    forecasts: dict[str, dict[str, list[Any]]] = {}
    for category, _ in ranked_categories:
        daily_prices = category_daily_prices.get(category, {})
        if len(daily_prices) < MIN_HISTORY_DAYS:
            continue

        time_series, last_date = _build_continuous_series(daily_prices)
        model_forecast = _try_arima_forecast(time_series)
        if model_forecast is None:
            model_forecast = _try_prophet_forecast(time_series)
        if model_forecast is None or not _is_complete_forecast(model_forecast):
            continue

        dates = [
            (last_date + timedelta(days=offset)).isoformat()
            for offset in range(1, FORECAST_HORIZON_DAYS + 1)
        ]
        forecasts[category] = {
            "dates": dates,
            "forecast": model_forecast["forecast"],
            "lower_80": model_forecast["lower_80"],
            "upper_80": model_forecast["upper_80"],
            "lower_95": model_forecast["lower_95"],
            "upper_95": model_forecast["upper_95"],
        }

    return forecasts


def _aggregate_daily_average_prices(
    deals: list[Deal],
) -> tuple[dict[str, dict[date, float]], dict[str, int]]:
    grouped_prices: dict[str, dict[date, list[float]]] = defaultdict(lambda: defaultdict(list))
    category_counts: dict[str, int] = defaultdict(int)

    for deal in deals:
        category = deal.category.strip() if isinstance(deal.category, str) else ""
        if not category:
            continue
        if not isinstance(deal.collected_at, datetime):
            continue
        try:
            price = float(deal.price)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue

        grouped_prices[category][deal.collected_at.date()].append(price)
        category_counts[category] += 1

    daily_average_prices: dict[str, dict[date, float]] = {}
    for category, by_day in grouped_prices.items():
        daily_average_prices[category] = {
            day: sum(values) / len(values) for day, values in by_day.items() if values
        }

    return daily_average_prices, category_counts


def _build_continuous_series(daily_prices: dict[date, float]) -> tuple[list[float], date]:
    sorted_dates = sorted(daily_prices)
    first_date = sorted_dates[0]
    last_date = sorted_dates[-1]

    series: list[float] = []
    current_date = first_date
    last_value = float(daily_prices[first_date])
    while current_date <= last_date:
        value = daily_prices.get(current_date)
        if value is None:
            series.append(last_value)
        else:
            last_value = float(value)
            series.append(last_value)
        current_date += timedelta(days=1)

    return series, last_date


def _try_arima_forecast(series: list[float]) -> dict[str, list[float]] | None:
    try:
        arima_module = importlib.import_module("statsmodels.tsa.arima.model")
        arima_class = getattr(arima_module, "ARIMA", None)
        if arima_class is None:
            return None
    except Exception:
        return None

    try:
        model = arima_class(series, order=(5, 1, 0))
        fitted_model = model.fit()
        mle_retvals = getattr(fitted_model, "mle_retvals", {})
        if isinstance(mle_retvals, dict) and not bool(mle_retvals.get("converged", True)):
            return None

        result = fitted_model.get_forecast(steps=FORECAST_HORIZON_DAYS)
        forecast = _to_non_negative_float_list(result.predicted_mean)
        lower_80, upper_80 = _extract_confidence_bounds(result.conf_int(alpha=0.2))
        lower_95, upper_95 = _extract_confidence_bounds(result.conf_int(alpha=0.05))
        return {
            "forecast": forecast,
            "lower_80": lower_80,
            "upper_80": upper_80,
            "lower_95": lower_95,
            "upper_95": upper_95,
        }
    except Exception:
        return None


def _try_prophet_forecast(series: list[float]) -> dict[str, list[float]] | None:
    try:
        pandas_module = importlib.import_module("pandas")
        prophet_module = importlib.import_module("prophet")
        dataframe_class = getattr(pandas_module, "DataFrame", None)
        prophet_class = getattr(prophet_module, "Prophet", None)
        if dataframe_class is None or prophet_class is None:
            return None
    except Exception:
        return None

    try:
        start = datetime(2000, 1, 1, tzinfo=UTC)
        history_dates = [start + timedelta(days=offset) for offset in range(len(series))]
        history_df = dataframe_class({"ds": history_dates, "y": series})

        model = prophet_class(
            interval_width=0.95,
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=False,
        )
        model.fit(history_df)

        future_df = model.make_future_dataframe(periods=FORECAST_HORIZON_DAYS, freq="D")
        forecast_df = model.predict(future_df).tail(FORECAST_HORIZON_DAYS)

        forecast = _to_non_negative_float_list(forecast_df["yhat"])
        lower_95 = _to_non_negative_float_list(forecast_df["yhat_lower"])
        upper_95 = _to_non_negative_float_list(forecast_df["yhat_upper"])
        lower_80, upper_80 = _derive_80_intervals(forecast, lower_95, upper_95)

        return {
            "forecast": forecast,
            "lower_80": lower_80,
            "upper_80": upper_80,
            "lower_95": lower_95,
            "upper_95": upper_95,
        }
    except Exception:
        return None


def _extract_confidence_bounds(conf_int: Any) -> tuple[list[float], list[float]]:
    if hasattr(conf_int, "iloc"):
        lower = _to_non_negative_float_list(conf_int.iloc[:, 0])
        upper = _to_non_negative_float_list(conf_int.iloc[:, 1])
        return lower, upper

    rows: list[Any]
    if hasattr(conf_int, "tolist"):
        rows = list(conf_int.tolist())
    else:
        rows = list(conf_int)

    lower_values: list[float] = []
    upper_values: list[float] = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            lower_values.append(float(row[0]))
            upper_values.append(float(row[1]))

    return _to_non_negative_float_list(lower_values), _to_non_negative_float_list(upper_values)


def _derive_80_intervals(
    center: list[float],
    lower_95: list[float],
    upper_95: list[float],
) -> tuple[list[float], list[float]]:
    ratio = Z_SCORE_80 / Z_SCORE_95
    lower_80: list[float] = []
    upper_80: list[float] = []

    for idx, center_value in enumerate(center):
        half_width_95 = max((upper_95[idx] - lower_95[idx]) / 2.0, 0.0)
        half_width_80 = half_width_95 * ratio
        lower_80.append(max(center_value - half_width_80, 0.0))
        upper_80.append(max(center_value + half_width_80, 0.0))

    return lower_80, upper_80


def _to_non_negative_float_list(values: Any) -> list[float]:
    raw_values: list[Any]
    if hasattr(values, "tolist"):
        raw_values = list(values.tolist())
    else:
        raw_values = list(values)

    normalized: list[float] = []
    for value in raw_values:
        number = float(value)
        normalized.append(max(number, 0.0))

    return normalized


def _is_complete_forecast(model_forecast: dict[str, list[float]]) -> bool:
    required_keys = ["forecast", "lower_80", "upper_80", "lower_95", "upper_95"]
    for key in required_keys:
        values = model_forecast.get(key)
        if values is None or len(values) != FORECAST_HORIZON_DAYS:
            return False
    return True
