from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Source:
    name: str
    type: str
    url: str


@dataclass
class EntityDefinition:
    name: str
    display_name: str
    keywords: list[str]


@dataclass
class Article:
    title: str
    link: str
    summary: str
    published: datetime | None
    source: str
    category: str
    matched_entities: dict[str, list[str]] = field(default_factory=dict)
    collected_at: datetime | None = None


@dataclass
class CategoryConfig:
    category_name: str
    display_name: str
    sources: list[Source]
    entities: list[EntityDefinition]


@dataclass
class RadarSettings:
    database_path: Path
    report_dir: Path
    raw_data_dir: Path
    search_db_path: Path


@dataclass
class EmailSettings:
    smtp_host: str
    smtp_port: int
    username: str
    password: str
    from_address: str
    to_addresses: list[str]


@dataclass
class TelegramSettings:
    bot_token: str
    chat_id: str


@dataclass
class NotificationConfig:
    enabled: bool
    channels: list[str]
    email: EmailSettings | None = None
    webhook_url: str | None = None
    telegram: TelegramSettings | None = None
    rules: dict[str, object] = field(default_factory=dict)


@dataclass
class Deal:
    price: float
    category: str
    collected_at: datetime


@dataclass
class Product:
    id: str
    title: str
    category: str
    brand: str | None
    source_platform: str
    product_url: str
    image_url: str | None
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class PriceSnapshot:
    product_id: str
    ts: datetime
    price: int
    avg_price_30d: int | None
    avg_price_90d: int | None
    discount_rate_vs_avg: float | None
    discount_rate_vs_list: float | None
    source: str
    meta: dict[str, object] = field(default_factory=dict)


@dataclass
class PriceEvent:
    product_id: str
    event_ts: datetime
    event_type: str
    drop_rate: float | None
    saving_vs_avg: int | None
    radar_score: float
    explanation: str
