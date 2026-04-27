from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable, Mapping
from html import escape
from pathlib import Path
from typing import Any, cast

from radar_core.ontology import build_summary_ontology_metadata

from .models import Article, CategoryConfig


def _load_core_report_utils() -> tuple[Callable[..., Path], Callable[..., Path]]:
    report_utils = importlib.import_module("radar_core.report_utils")
    generate_index_html = report_utils.generate_index_html
    generate_report = report_utils.generate_report
    if not callable(generate_index_html) or not callable(generate_report):
        raise TypeError("radar_core.report_utils is missing required callables")
    return cast(Callable[..., Path], generate_index_html), cast(
        Callable[..., Path], generate_report
    )


def generate_report(
    *,
    category: CategoryConfig,
    articles: Iterable[Article],
    output_path: Path,
    stats: dict[str, int],
    errors: list[str] | None = None,
    store=None,
    quality_report: Mapping[str, Any] | None = None,
) -> Path:
    """Generate HTML report (delegates to radar-core)."""
    _, core_generate_report = _load_core_report_utils()
    articles_list = list(articles)
    plugin_charts = []
    extra_sections: list[dict[str, Any]] = []

    # --- Universal plugins (entity heatmap + source reliability) ---
    try:
        _heatmap_module = importlib.import_module("radar_core.plugins.entity_heatmap")
        _heatmap_config = _heatmap_module.get_chart_config
        if not callable(_heatmap_config):
            raise TypeError("entity_heatmap.get_chart_config is not callable")

        _heatmap = _heatmap_config(articles=articles_list)
        if _heatmap is not None:
            plugin_charts.append(_heatmap)
    except Exception:
        pass
    try:
        _reliability_module = importlib.import_module("radar_core.plugins.source_reliability")
        _reliability_config = _reliability_module.get_chart_config
        if not callable(_reliability_config):
            raise TypeError("source_reliability.get_chart_config is not callable")

        _reliability = _reliability_config(store=store)
        if _reliability is not None:
            plugin_charts.append(_reliability)
    except Exception:
        pass
    if quality_report:
        extra_sections.append(_build_price_quality_section(quality_report))

    return core_generate_report(
        category=category,
        articles=articles_list,
        output_path=output_path,
        stats=stats,
        errors=errors,
        plugin_charts=plugin_charts if plugin_charts else None,
        extra_sections=extra_sections or None,
        ontology_metadata=build_summary_ontology_metadata(
            "PriceRadar",
            category_name=category.category_name,
            search_from=Path(__file__).resolve(),
        ),
    )


def generate_index_html(report_dir: Path, summaries_dir: Path | None = None) -> Path:
    """Generate index.html (delegates to radar-core)."""
    core_generate_index_html, _core_generate_report = _load_core_report_utils()
    radar_name = "Price Radar"
    return core_generate_index_html(report_dir, radar_name)


def _build_price_quality_section(quality_report: Mapping[str, Any]) -> dict[str, Any]:
    summary = quality_report.get("summary")
    summary_map = summary if isinstance(summary, Mapping) else {}
    events = [row for row in _list(quality_report.get("events")) if isinstance(row, Mapping)]
    review_items = [
        row
        for row in _list(quality_report.get("daily_review_items"))
        if isinstance(row, Mapping)
    ]
    official_backlog = [
        row
        for row in _list(quality_report.get("official_source_backlog"))
        if isinstance(row, Mapping)
    ]
    chips = [
        ("sku events", summary_map.get("sku_price_snapshot_events", 0)),
        ("benefits", summary_map.get("purchase_benefit_snapshot_events", 0)),
        ("stock", summary_map.get("stock_status_transition_events", 0)),
        ("official backlog", summary_map.get("official_source_backlog_count", 0)),
        ("authority review", summary_map.get("authority_gap_review_count", 0)),
        ("outliers", summary_map.get("outlier_event_count", 0)),
        ("review", summary_map.get("daily_review_item_count", 0)),
    ]
    chip_html = "\n".join(
        f'<span class="chip"><strong>{escape(label)}</strong> {escape(str(value))}</span>'
        for label, value in chips
    )
    return {
        "id": "price-quality",
        "title": "Price Quality",
        "panel_title": "Price Event Coverage",
        "subtitle": "SKU price snapshots, purchase benefits, stock status, and daily review items.",
        "badges": ["price_quality.json", "sku-contract", "review"],
        "body_html": (
            f"<div class=\"inline-chips\">{chip_html}</div>"
            "<div><h3>Observed Events</h3>"
            f"{_render_price_events(events[:6])}"
            "</div>"
            "<div><h3>Daily Review</h3>"
            f"{_render_daily_review_items(review_items[:6])}"
            "</div>"
            "<div><h3>Official Backlog</h3>"
            f"{_render_official_backlog(official_backlog[:6])}"
            "</div>"
        ),
    }


def _render_price_events(events: list[Mapping[str, Any]]) -> str:
    if not events:
        return '<p class="muted small">No tracked price events in this run.</p>'
    items = []
    for row in events:
        model = escape(str(row.get("event_model", "")))
        title = escape(str(row.get("title", ""))[:120])
        source = escape(str(row.get("source_id", "")))
        effective = row.get("effective_price")
        stock = row.get("stock_status")
        price_text = "" if effective is None else f", effective {escape(str(effective))}"
        stock_text = "" if not stock else f", stock {escape(str(stock))}"
        items.append(f"<li><strong>{model}</strong> {source}: {title}{price_text}{stock_text}</li>")
    return "<ul>" + "\n".join(items) + "</ul>"


def _render_daily_review_items(review_items: list[Mapping[str, Any]]) -> str:
    if not review_items:
        return '<p class="muted small">No price outlier or exception review items in this run.</p>'
    items = []
    for row in review_items:
        reasons = ", ".join(escape(str(reason)) for reason in _list(row.get("reason")))
        title = escape(str(row.get("title", ""))[:120])
        product_id = escape(str(row.get("product_id", "")))
        items.append(f"<li><strong>{reasons}</strong> {product_id}: {title}</li>")
    return "<ul>" + "\n".join(items) + "</ul>"


def _render_official_backlog(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return '<p class="muted small">No official brand/store backlog configured.</p>'
    items = []
    for row in rows:
        name = escape(str(row.get("name") or row.get("id") or ""))
        domains = ", ".join(escape(str(domain)) for domain in _list(row.get("representative_domains")))
        gate = escape(str(row.get("activation_gate") or ""))
        suffix = f" ({domains})" if domains else ""
        detail = f": {gate}" if gate else ""
        items.append(f"<li><strong>{name}</strong>{suffix}{detail}</li>")
    return "<ul>" + "\n".join(items) + "</ul>"


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
