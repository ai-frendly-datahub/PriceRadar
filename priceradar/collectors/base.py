"""
Base collector 모듈 - 모든 수집기의 기본 인터페이스
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests

from priceradar.resilience import SourceCircuitBreakerManager
from priceradar.validators import (
    validate_discount_rate,
    validate_price_range,
    validate_url_format,
)


@dataclass
class RawItem:
    """수집한 원시 데이터 아이템"""

    product_id: str
    title: str
    url: str
    source: str
    collected_at: datetime = field(default_factory=datetime.now)

    current_price: int | None = None
    avg_price: int | None = None
    list_price: int | None = None
    discount_rate: float | None = None

    category: str | None = None
    platform: str | None = None
    image_url: str | None = None
    brand: str | None = None

    is_hotdeal: bool = False
    is_popular: bool = False
    is_lowest_now: bool = False

    raw_data: dict[str, Any] = field(default_factory=dict)


class BaseCollector(ABC):
    """모든 수집기의 기본 클래스"""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        self.source_id = source_id
        self.config = config
        self.breaker_manager = SourceCircuitBreakerManager()

    def _resolve_source_name(self) -> str:
        source_name = self.config.get("name")
        if isinstance(source_name, str) and source_name:
            return source_name
        return self.source_id

    def _resolve_timeout(self) -> float:
        timeout = self.config.get("timeout", 30)
        if isinstance(timeout, (int, float)):
            return float(timeout)
        return 30.0

    def _fetch(self, url: str) -> requests.Response:
        source_name = self._resolve_source_name()
        breaker = self.breaker_manager.get_breaker(source_name)

        def _fetch_impl() -> requests.Response:
            response = requests.get(url, timeout=self._resolve_timeout())
            response.raise_for_status()
            return response

        return breaker.call(
            lambda source=source_name: _fetch_impl(),
            source=source_name,
        )

    def _fetch_html(self, url: str) -> str | None:
        source_name = self._resolve_source_name()
        breaker = self.breaker_manager.get_breaker(source_name)

        def _fetch_html_impl() -> str | None:
            response = requests.get(url, timeout=self._resolve_timeout())
            response.raise_for_status()
            # charset meta 태그를 우선으로 encoding 감지
            if response.encoding is None or not response.encoding:
                response.encoding = response.apparent_encoding or "utf-8"
            return response.text

        return breaker.call(
            lambda source=source_name: _fetch_html_impl(),
            source=source_name,
        )

    def _fetch_json(self, url: str) -> dict[str, Any] | list[Any]:
        source_name = self._resolve_source_name()
        breaker = self.breaker_manager.get_breaker(source_name)

        def _fetch_json_impl() -> dict[str, Any] | list[Any]:
            response = requests.get(url, timeout=self._resolve_timeout())
            response.raise_for_status()
            return response.json()

        return breaker.call(
            lambda source=source_name: _fetch_json_impl(),
            source=source_name,
        )

    @abstractmethod
    def collect(self) -> list[RawItem]:
        """데이터를 수집하고 RawItem 리스트를 반환"""
        pass

    def validate_item(self, item: RawItem) -> bool:
        # 필수 필드 검증
        if not item.product_id or not item.title or not item.url:
            return False

        # URL 형식 검증
        if not validate_url_format(item.url):
            return False

        # 가격 범위 검증 (None 허용 - 선택적 필드)
        if item.current_price is not None and not validate_price_range(item.current_price):
            return False

        if item.avg_price is not None and not validate_price_range(item.avg_price):
            return False

        if item.list_price is not None and not validate_price_range(item.list_price):
            return False

        # 할인율 검증 (None 허용)
        if item.discount_rate is not None and not validate_discount_rate(item.discount_rate):
            return False

        return True
