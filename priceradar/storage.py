from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import duckdb

from .exceptions import StorageError
from .models import PriceEvent, PriceSnapshot, Product
from .validators import detect_duplicate_products, normalize_title


def _utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class PriceStorage:
    """DuckDB 저장/업서트 헬퍼."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = duckdb.connect(str(self.db_path))
        self._ensure_tables()

    def close(self) -> None:
        self.conn.close()

    def _ensure_tables(self) -> None:
        self.conn.execute(
            """
            CREATE SEQUENCE IF NOT EXISTS product_id_seq START 1;
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT,
                brand TEXT,
                source_platform TEXT,
                product_url TEXT,
                image_url TEXT,
                attributes_json TEXT
            );
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id BIGINT PRIMARY KEY DEFAULT nextval('product_id_seq'),
                product_id TEXT NOT NULL,
                ts TIMESTAMP NOT NULL,
                price INTEGER NOT NULL,
                avg_price_30d INTEGER,
                avg_price_90d INTEGER,
                discount_rate_vs_avg DOUBLE,
                discount_rate_vs_list DOUBLE,
                source TEXT,
                meta_json TEXT
            );
            CREATE TABLE IF NOT EXISTS price_events (
                id BIGINT PRIMARY KEY DEFAULT nextval('product_id_seq'),
                product_id TEXT NOT NULL,
                event_ts TIMESTAMP NOT NULL,
                event_type TEXT NOT NULL,
                drop_rate DOUBLE,
                saving_vs_avg INTEGER,
                radar_score DOUBLE NOT NULL,
                explanation TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_product_ts ON price_snapshots (product_id, ts);
            CREATE INDEX IF NOT EXISTS idx_events_product_ts ON price_events (product_id, event_ts);
            """
        )

    def upsert_products(self, products: Iterable[Product]) -> None:
        """
        Upsert products with duplicate detection.

        Detects duplicates based on normalized title and URL similarity.
        If a duplicate is found, the existing product is updated instead of creating a new one.
        """
        try:
            self.conn.execute("BEGIN TRANSACTION")
            for p in products:
                existing_duplicate = self._find_duplicate_product(p)

                if existing_duplicate:
                    product_id = existing_duplicate
                else:
                    product_id = p.id

                attr_json = json.dumps(p.attributes, ensure_ascii=False) if p.attributes else None
                self.conn.execute(
                    """
                    INSERT INTO products (
                        id, title, category, brand, source_platform, product_url, image_url, attributes_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        category = EXCLUDED.category,
                        brand = EXCLUDED.brand,
                        source_platform = EXCLUDED.source_platform,
                        product_url = EXCLUDED.product_url,
                        image_url = EXCLUDED.image_url,
                        attributes_json = EXCLUDED.attributes_json
                    """,
                    [
                        product_id,
                        p.title,
                        p.category,
                        p.brand,
                        p.source_platform,
                        p.product_url,
                        p.image_url,
                        attr_json,
                    ],
                )
            self.conn.execute("COMMIT")
        except duckdb.Error as exc:
            self.conn.execute("ROLLBACK")
            raise StorageError(f"Failed to upsert products: {exc}") from exc

    def _find_duplicate_product(self, product: Product) -> Optional[str]:
        """
        Find existing product that is a duplicate of the given product.

        Returns the ID of the duplicate product if found, None otherwise.
        """
        try:
            result = self.conn.execute(
                "SELECT id, title, product_url FROM products LIMIT 1000"
            ).fetchall()

            for existing_id, existing_title, existing_url in result:
                if detect_duplicate_products(
                    product.title,
                    product.product_url,
                    existing_title,
                    existing_url,
                ):
                    return existing_id

            return None
        except Exception:
            return None

    def insert_snapshots(self, snapshots: Iterable[PriceSnapshot]) -> int:
        count = 0
        try:
            self.conn.execute("BEGIN TRANSACTION")
            for s in snapshots:
                meta_json = json.dumps(s.meta, ensure_ascii=False) if s.meta else None
                self.conn.execute(
                    """
                    INSERT INTO price_snapshots (
                        product_id, ts, price, avg_price_30d, avg_price_90d,
                        discount_rate_vs_avg, discount_rate_vs_list, source, meta_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        s.product_id,
                        _utc_naive(s.ts),
                        s.price,
                        s.avg_price_30d,
                        s.avg_price_90d,
                        s.discount_rate_vs_avg,
                        s.discount_rate_vs_list,
                        s.source,
                        meta_json,
                    ],
                )
                count += 1
            self.conn.execute("COMMIT")
            return count
        except duckdb.Error as exc:
            self.conn.execute("ROLLBACK")
            raise StorageError(f"Failed to insert price snapshots: {exc}") from exc

    def insert_events(self, events: Iterable[PriceEvent]) -> int:
        count = 0
        try:
            self.conn.execute("BEGIN TRANSACTION")
            for e in events:
                self.conn.execute(
                    """
                    INSERT INTO price_events (
                        product_id, event_ts, event_type, drop_rate, saving_vs_avg, radar_score, explanation
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        e.product_id,
                        _utc_naive(e.event_ts),
                        e.event_type,
                        e.drop_rate,
                        e.saving_vs_avg,
                        e.radar_score,
                        e.explanation,
                    ],
                )
                count += 1
            self.conn.execute("COMMIT")
            return count
        except duckdb.Error as exc:
            self.conn.execute("ROLLBACK")
            raise StorageError(f"Failed to insert price events: {exc}") from exc

    def create_daily_snapshot(self, snapshot_dir: Optional[str] = None) -> Optional[Path]:
        from .date_storage import snapshot_database

        snapshot_root = Path(snapshot_dir) if snapshot_dir else self.db_path.parent / "daily"
        return snapshot_database(self.db_path, snapshot_root=snapshot_root)

    def cleanup_old_snapshots(self, snapshot_dir: Optional[str] = None, keep_days: int = 90) -> int:
        from .date_storage import cleanup_date_directories

        snapshot_root = Path(snapshot_dir) if snapshot_dir else self.db_path.parent / "daily"
        return cleanup_date_directories(snapshot_root, keep_days=keep_days)
