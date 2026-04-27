"""Plotly price forecast plugin for PriceRadar unified template."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from priceradar.graph.graph_store import GraphStore


def get_chart_config(store: GraphStore | None = None, articles: Any = None) -> dict | None:
    """Generate Plotly price forecast chart config for plugin slot.

    Args:
        store: GraphStore instance to fetch top deals from.
        articles: Unused (kept for API compatibility).

    Returns:
        Plugin chart config dict with id, title, config_json, or None on failure.
    """
    try:
        if store is None:
            return None

        deals = store.get_top_deals(limit=200)
        if not deals:
            return None

        from priceradar.reporters.html_reporter import HtmlReporter

        reporter = HtmlReporter.__new__(HtmlReporter)
        forecast_data = reporter._build_forecast_data(deals)
        history_data = reporter._build_forecast_history(deals, set(forecast_data.keys()))

        if not forecast_data:
            return None

        import plotly.graph_objects as go

        forecast_categories = list(forecast_data.keys())
        traces: list[Any] = []
        layout: dict[str, Any] = {
            "height": max(420, len(forecast_categories) * 240),
            "showlegend": True,
            "legend": {"orientation": "h", "x": 0, "y": 1.08},
            "margin": {"l": 60, "r": 20, "t": 24, "b": 40},
            "paper_bgcolor": "rgba(10,14,23,0)",
            "plot_bgcolor": "rgba(14,22,42,0.5)",
            "font": {"color": "#e9eefb"},
        }

        for index, category in enumerate(forecast_categories):
            axis_id = index + 1
            axis_suffix = "" if axis_id == 1 else str(axis_id)
            x_axis_name = "x" if axis_id == 1 else f"x{axis_id}"
            y_axis_name = "y" if axis_id == 1 else f"y{axis_id}"
            item = forecast_data.get(category, {})
            category_history = history_data.get(category, {"history_dates": [], "history_avg": []})
            history_dates = category_history.get("history_dates", [])
            history_avg = category_history.get("history_avg", [])
            dates = item.get("dates", [])
            forecast = item.get("forecast", [])
            lower_80 = item.get("lower_80", [])
            upper_80 = item.get("upper_80", [])
            lower_95 = item.get("lower_95", [])
            upper_95 = item.get("upper_95", [])
            show_legend = index == 0

            # 95% CI band
            traces.append(
                go.Scatter(
                    x=dates,
                    y=upper_95,
                    mode="lines",
                    line={"color": "rgba(255,165,0,0)"},
                    hoverinfo="skip",
                    showlegend=False,
                    xaxis=x_axis_name,
                    yaxis=y_axis_name,
                )
            )
            traces.append(
                go.Scatter(
                    x=dates,
                    y=lower_95,
                    mode="lines",
                    line={"color": "rgba(255,165,0,0)"},
                    fill="tonexty",
                    fillcolor="rgba(255,165,0,0.12)",
                    name="95% CI",
                    showlegend=show_legend,
                    xaxis=x_axis_name,
                    yaxis=y_axis_name,
                )
            )
            # 80% CI band
            traces.append(
                go.Scatter(
                    x=dates,
                    y=upper_80,
                    mode="lines",
                    line={"color": "rgba(255,165,0,0)"},
                    hoverinfo="skip",
                    showlegend=False,
                    xaxis=x_axis_name,
                    yaxis=y_axis_name,
                )
            )
            traces.append(
                go.Scatter(
                    x=dates,
                    y=lower_80,
                    mode="lines",
                    line={"color": "rgba(255,165,0,0)"},
                    fill="tonexty",
                    fillcolor="rgba(255,165,0,0.2)",
                    name="80% CI",
                    showlegend=show_legend,
                    xaxis=x_axis_name,
                    yaxis=y_axis_name,
                )
            )
            # Historical average
            traces.append(
                go.Scatter(
                    x=history_dates,
                    y=history_avg,
                    mode="lines",
                    line={"color": "#4a9eff", "width": 2},
                    name="Historical avg",
                    showlegend=show_legend,
                    xaxis=x_axis_name,
                    yaxis=y_axis_name,
                )
            )
            # Forecast line
            traces.append(
                go.Scatter(
                    x=dates,
                    y=forecast,
                    mode="lines",
                    line={"color": "#ff8c00", "width": 2, "dash": "dash"},
                    name="Forecast",
                    showlegend=show_legend,
                    xaxis=x_axis_name,
                    yaxis=y_axis_name,
                )
            )

            x_axis_config: dict[str, Any] = {
                "type": "date",
                "showgrid": True,
                "gridcolor": "rgba(233,238,251,0.1)",
                "title": "Date" if axis_id == len(forecast_categories) else "",
                "showticklabels": axis_id == len(forecast_categories),
                "color": "#e9eefb",
            }
            if axis_id > 1:
                x_axis_config["matches"] = "x"
            layout[f"xaxis{axis_suffix}"] = x_axis_config
            layout[f"yaxis{axis_suffix}"] = {
                "title": f"{category} (KRW)",
                "showgrid": True,
                "gridcolor": "rgba(233,238,251,0.1)",
                "color": "#e9eefb",
            }

        fig = go.Figure(data=traces, layout=layout)

        import plotly.io as pio

        config_json = pio.to_html(fig, full_html=False, include_plotlyjs="cdn")

        return {
            "id": "price_forecast",
            "title": "Price Forecast (14-day ahead)",
            "config_json": config_json,
        }

    except Exception:
        return None
