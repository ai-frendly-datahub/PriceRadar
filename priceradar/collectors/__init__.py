from __future__ import annotations

from importlib import import_module
from typing import Any

from priceradar.collectors.base import BaseCollector, RawItem
from priceradar.collectors.registry import CollectorRegistry

_COLLECTOR_MODULES = {
    "HtmlCollector": "priceradar.collectors.html_collector",
    "AlgumonCollector": "priceradar.collectors.algumon_collector",
    "FallcentCollector": "priceradar.collectors.fallcent_collector",
    "FallcentCategoryCollector": "priceradar.collectors.fallcent_collector",
    "EnuriCollector": "priceradar.collectors.enuri_collector",
    "EnuriCategoryCollector": "priceradar.collectors.enuri_collector",
    "QuasarzoneCollector": "priceradar.collectors.quasarzone_collector",
    "RuliwebCollector": "priceradar.collectors.ruliweb_collector",
}


def __getattr__(name: str) -> Any:
    module_path = _COLLECTOR_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    module = import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "BaseCollector",
    "RawItem",
    "HtmlCollector",
    "AlgumonCollector",
    "FallcentCollector",
    "FallcentCategoryCollector",
    "EnuriCollector",
    "EnuriCategoryCollector",
    "QuasarzoneCollector",
    "RuliwebCollector",
    "CollectorRegistry",
]
