"""
수집기 레지스트리 - 소스 설정에 따라 적절한 수집기를 생성
"""

from typing import Any

from priceradar.collectors.base import BaseCollector
from priceradar.collectors.enuri_collector import EnuriCategoryCollector, EnuriCollector
from priceradar.collectors.fallcent_collector import (
    FallcentCategoryCollector,
    FallcentCollector,
)
from priceradar.collectors.html_collector import HtmlCollector


class CollectorRegistry:
    """수집기 팩토리 - 설정에 따라 적절한 수집기 인스턴스를 생성"""

    COLLECTOR_MAP = {
        # 기본 HTML 파서
        "C2_html_simple": HtmlCollector,
        # 폴센트 전용
        "C3_fallcent": FallcentCollector,
        "C3_fallcent_category": FallcentCategoryCollector,
        # 에누리 전용
        "C3_enuri": EnuriCollector,
        "C3_enuri_category": EnuriCategoryCollector,
    }

    @classmethod
    def create_collector(cls, source_config: dict[str, Any]) -> BaseCollector:
        """소스 설정을 기반으로 수집기 인스턴스 생성"""
        source_id = source_config.get("id", "unknown")
        collector_type = source_config.get("collector_type", "C2_html_simple")

        collector_class = cls.COLLECTOR_MAP.get(collector_type)
        if not collector_class:
            raise ValueError(f"지원하지 않는 collector_type: {collector_type}")

        return collector_class(source_id, source_config)
