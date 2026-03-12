"""
Base collector 모듈 - 모든 수집기의 기본 인터페이스
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import os
import threading
import time
from typing import Any, Optional, Union
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

    current_price: Optional[int] = None
    avg_price: Optional[int] = None
    list_price: Optional[int] = None
    discount_rate: Optional[float] = None

    category: Optional[str] = None
    platform: Optional[str] = None
    image_url: Optional[str] = None
    brand: Optional[str] = None

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
        self._session = _create_session()
        self._rate_limiters: dict[str, RateLimiter] = {}

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        source_name = self._resolve_source_name()
        breaker = self.breaker_manager.get_breaker(source_name)
        timeout = kwargs.pop("timeout", self._resolve_timeout())
        min_interval = self.config.get("request_interval", 0.5)
        if not isinstance(min_interval, (int, float)):
            min_interval = 0.5

        host = urlparse(url).netloc.lower() or source_name
        limiter = self._rate_limiters.setdefault(host, RateLimiter(float(min_interval)))

        def _request_impl() -> requests.Response:
            limiter.acquire()
            if method.upper() == "POST":
                response = requests.post(url, timeout=timeout, **kwargs)
            else:
                response = requests.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response

        return breaker.call(
            lambda source=source_name: _request_impl(),
            source=source_name,
        )

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
        return self._request("GET", url)

    def _fetch_html(self, url: str) -> Optional[str]:
        response = self._request("GET", url)
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def _fetch_json(self, url: str) -> Union[dict[str, Any], list[Any]]:
        response = self._request("GET", url)
        return response.json()

    @abstractmethod
    def collect(self) -> list[RawItem]:
        """데이터를 수집하고 RawItem 리스트를 반환"""
        pass

    def validate_item(self, item: RawItem) -> bool:
        if not item.product_id or not item.title or not item.url:
            return False

        if not validate_url_format(item.url):
            return False

        if not validate_price_range(item.current_price):
            return False

        if not validate_price_range(item.avg_price):
            return False

        if not validate_price_range(item.list_price):
            return False

        if not validate_discount_rate(item.discount_rate):
            return False

        return True


class RateLimiter:
    def __init__(self, min_interval: float = 0.5):
        self._min_interval = min_interval
        self._last_request = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()


def resolve_max_workers(max_workers: Optional[int] = None) -> int:
    if max_workers is None:
        raw_value = os.environ.get("RADAR_MAX_WORKERS", "5")
        try:
            parsed = int(raw_value)
        except ValueError:
            parsed = 5
    else:
        parsed = max_workers

    return max(1, min(parsed, 10))


def _create_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
