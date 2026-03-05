"""
Base collector 모듈 - 모든 수집기의 기본 인터페이스
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from priceradar.validators import (
    validate_discount_rate,
    validate_price_range,
    validate_url_format,
)


@dataclass
class RawItem:
    """수집한 원시 데이터 아이템"""

    product_id: str  # 상품 고유 ID
    title: str  # 상품명
    url: str  # 상품 URL
    source: str  # 데이터 소스 (예: fallcent_main)
    collected_at: datetime = field(default_factory=datetime.now)

    # 가격 정보
    current_price: Optional[int] = None  # 현재 가격
    avg_price: Optional[int] = None  # 평균 가격
    list_price: Optional[int] = None  # 정가
    discount_rate: Optional[float] = None  # 할인율

    # 메타데이터
    category: Optional[str] = None  # 카테고리
    platform: Optional[str] = None  # 쇼핑몰 (coupang, naver 등)
    image_url: Optional[str] = None  # 이미지 URL
    brand: Optional[str] = None  # 브랜드

    # 추가 정보
    is_hotdeal: bool = False  # 핫딜 여부
    is_popular: bool = False  # 인기 상품 여부
    is_lowest_now: bool = False  # 현재 최저가 여부

    # 원시 데이터
    raw_data: dict[str, Any] = field(default_factory=dict)


class BaseCollector(ABC):
    """모든 수집기의 기본 클래스"""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        self.source_id = source_id
        self.config = config

    @abstractmethod
    def collect(self) -> list[RawItem]:
        """데이터를 수집하고 RawItem 리스트를 반환"""
        pass

    def validate_item(self, item: RawItem) -> bool:
        """
        수집한 아이템의 유효성을 검증.

        검증 항목:
        - 필수 필드: product_id, title, url
        - URL 형식 유효성
        - 가격 범위 (100원 ~ 10억 원)
        - 할인율 범위 (0.0 ~ 1.0)
        """
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
