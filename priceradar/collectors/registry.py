from __future__ import annotations

from importlib import import_module
from typing import Any

from priceradar.collectors.base import BaseCollector


class CollectorRegistry:
    COLLECTOR_MAP: dict[str, tuple[str, str]] = {
        "C2_html_simple": ("priceradar.collectors.html_collector", "HtmlCollector"),
        "C3_fallcent": ("priceradar.collectors.fallcent_collector", "FallcentCollector"),
        "C3_fallcent_category": (
            "priceradar.collectors.fallcent_collector",
            "FallcentCategoryCollector",
        ),
        "C3_enuri": ("priceradar.collectors.enuri_collector", "EnuriCollector"),
        "C3_enuri_category": ("priceradar.collectors.enuri_collector", "EnuriCategoryCollector"),
        "C3_algumon": ("priceradar.collectors.algumon_collector", "AlgumonCollector"),
        "C3_quasarzone": ("priceradar.collectors.quasarzone_collector", "QuasarzoneCollector"),
        "C3_ruliweb": ("priceradar.collectors.ruliweb_collector", "RuliwebCollector"),
    }

    @classmethod
    def create_collector(cls, source_config: dict[str, Any]) -> BaseCollector:
        source_id = str(source_config.get("id", "unknown"))
        collector_type = str(source_config.get("collector_type", "C2_html_simple"))

        collector_spec = cls.COLLECTOR_MAP.get(collector_type)
        if collector_spec is None:
            raise ValueError(f"지원하지 않는 collector_type: {collector_type}")

        module_path, class_name = collector_spec
        collector_module = import_module(module_path)
        collector_class = getattr(collector_module, class_name, None)

        if not isinstance(collector_class, type) or not issubclass(collector_class, BaseCollector):
            raise TypeError(f"수집기 클래스 로드 실패: {module_path}.{class_name}")

        return collector_class(source_id, source_config)
