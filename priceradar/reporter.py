from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import cast

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
) -> Path:
    """Generate HTML report (delegates to radar-core)."""
    _, core_generate_report = _load_core_report_utils()
    articles_list = list(articles)
    plugin_charts = []

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

    return core_generate_report(
        category=category,
        articles=articles_list,
        output_path=output_path,
        stats=stats,
        errors=errors,
        plugin_charts=plugin_charts if plugin_charts else None,
    )


def generate_index_html(report_dir: Path, summaries_dir: Path | None = None) -> Path:
    """Generate index.html (delegates to radar-core)."""
    core_generate_index_html, _core_generate_report = _load_core_report_utils()
    radar_name = "Price Radar"
    return core_generate_index_html(report_dir, radar_name)
