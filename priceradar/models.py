from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class Product:
    id: str
    title: str
    category: str
    brand: Optional[str]
    source_platform: str
    product_url: str
    image_url: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PriceSnapshot:
    product_id: str
    ts: datetime
    price: int
    avg_price_30d: Optional[int] = None
    avg_price_90d: Optional[int] = None
    discount_rate_vs_avg: Optional[float] = None
    discount_rate_vs_list: Optional[float] = None
    source: str = "fallcent"
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PriceEvent:
    product_id: str
    event_ts: datetime
    event_type: str  # NEW_LOW | BIG_DROP | POPULAR_SPIKE
    drop_rate: Optional[float]
    saving_vs_avg: Optional[int]
    radar_score: float
    explanation: str


@dataclass
class Deal:
    price: float
    category: str
    collected_at: datetime
