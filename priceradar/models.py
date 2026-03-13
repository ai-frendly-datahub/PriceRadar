from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Product:
    id: str
    title: str
    category: str
    brand: str | None
    source_platform: str
    product_url: str
    image_url: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class PriceSnapshot:
    product_id: str
    ts: datetime
    price: int
    avg_price_30d: int | None = None
    avg_price_90d: int | None = None
    discount_rate_vs_avg: float | None = None
    discount_rate_vs_list: float | None = None
    source: str = "fallcent"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PriceEvent:
    product_id: str
    event_ts: datetime
    event_type: str  # NEW_LOW | BIG_DROP | POPULAR_SPIKE
    drop_rate: float | None
    saving_vs_avg: int | None
    radar_score: float
    explanation: str


@dataclass
class Deal:
    price: float
    category: str
    collected_at: datetime
