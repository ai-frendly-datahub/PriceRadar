from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import duckdb

from .exceptions import StorageError
from .models import Article, PriceEvent, PriceSnapshot, Product


def _utc_naive(dt: datetime | None) -> datetime | None:
    """Convert tz-aware datetime to UTC naive for DuckDB."""
    if dt is None:
        return None
    if dt.tzinfo:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


class RadarStorage:
    """DuckDB 기반 경량 스토리지."""

    def __init__(self, db_path: Path):
        self.db_path: Path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: duckdb.DuckDBPyConnection = duckdb.connect(str(self.db_path))
        self._ensure_tables()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> RadarStorage:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _ensure_tables(self) -> None:
        _ = self.conn.execute(
            """
            CREATE SEQUENCE IF NOT EXISTS articles_id_seq START 1;
            CREATE TABLE IF NOT EXISTS articles (
                id BIGINT PRIMARY KEY DEFAULT nextval('articles_id_seq'),
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL UNIQUE,
                summary TEXT,
                published TIMESTAMP,
                collected_at TIMESTAMP NOT NULL,
                entities_json TEXT
            );
            """
        )
        _ = self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_category_time ON articles (category, published, collected_at);"
        )

    def upsert_articles(self, articles: Iterable[Article]) -> None:
        """중복 링크는 덮어쓰고 최신 수집 시각을 기록."""
        now = _utc_naive(datetime.now(UTC))
        rows: list[tuple[object, ...]] = []
        for article in articles:
            rows.append(
                (
                    article.category,
                    article.source,
                    article.title,
                    article.link,
                    article.summary,
                    _utc_naive(article.published),
                    now,
                    json.dumps(article.matched_entities, ensure_ascii=False),
                )
            )

        if not rows:
            return

        try:
            _ = self.conn.begin()
            _ = self.conn.executemany(
                """
                INSERT INTO articles (category, source, title, link, summary, published, collected_at, entities_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(link) DO UPDATE SET
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    published = EXCLUDED.published,
                    collected_at = EXCLUDED.collected_at,
                    entities_json = EXCLUDED.entities_json
                """,
                rows,
            )
            _ = self.conn.commit()
        except Exception as exc:
            try:
                _ = self.conn.rollback()
            except duckdb.Error:
                pass
            raise StorageError("Failed to upsert articles") from exc

    def recent_articles(self, category: str, *, days: int = 7, limit: int = 200) -> list[Article]:
        """최근 N일 내 기사 반환."""
        since = _utc_naive(datetime.now(UTC) - timedelta(days=days))
        cur = self.conn.execute(
            """
            SELECT category, source, title, link, summary, published, collected_at, entities_json
            FROM articles
            WHERE category = ? AND COALESCE(published, collected_at) >= ?
            ORDER BY COALESCE(published, collected_at) DESC
            LIMIT ?
            """,
            [category, since, limit],
        )
        rows = cast(
            list[
                tuple[str, str, str, str, str | None, datetime | None, datetime | None, str | None]
            ],
            cur.fetchall(),
        )

        results: list[Article] = []
        for row in rows:
            category_value, source, title, link, summary, published, collected_at, raw_entities = (
                row
            )
            published_at = published if isinstance(published, datetime) else None
            collected = collected_at if isinstance(collected_at, datetime) else None

            entities: dict[str, list[str]] = {}
            if raw_entities:
                try:
                    parsed_entities = cast(object, json.loads(raw_entities))
                    if isinstance(parsed_entities, dict):
                        parsed_map = cast(dict[object, object], parsed_entities)
                        entities = {}
                        for name, keywords in parsed_map.items():
                            if not isinstance(name, str) or not isinstance(keywords, list):
                                continue
                            normalized_keywords: list[str] = []
                            for keyword in cast(list[object], keywords):
                                normalized_keywords.append(str(keyword))
                            entities[name] = normalized_keywords
                except json.JSONDecodeError:
                    entities = {}

            results.append(
                Article(
                    title=str(title),
                    link=str(link),
                    summary=str(summary) if summary is not None else "",
                    published=published_at,
                    source=str(source),
                    category=str(category_value),
                    matched_entities=entities,
                    collected_at=collected,
                )
            )
        return results

    def delete_older_than(self, days: int) -> int:
        """보존 기간 밖 데이터 삭제."""
        cutoff = _utc_naive(datetime.now(UTC) - timedelta(days=days))
        count_row = self.conn.execute(
            "SELECT COUNT(*) FROM articles WHERE COALESCE(published, collected_at) < ?", [cutoff]
        ).fetchone()
        to_delete = count_row[0] if count_row else 0
        _ = self.conn.execute(
            "DELETE FROM articles WHERE COALESCE(published, collected_at) < ?", [cutoff]
        )
        return to_delete

    def create_daily_snapshot(
        self,
        snapshot_dir: str | None = None,
        snapshot_date: date | None = None,
    ) -> Path | None:
        from .date_storage import snapshot_database

        snapshot_root = Path(snapshot_dir) if snapshot_dir else self.db_path.parent / "snapshots"
        _ = self.conn.execute("CHECKPOINT")
        self.conn.close()
        try:
            return snapshot_database(
                self.db_path,
                snapshot_date=snapshot_date,
                snapshot_root=snapshot_root,
            )
        finally:
            self.conn = duckdb.connect(str(self.db_path))
            self._ensure_tables()

    def cleanup_old_snapshots(self, snapshot_dir: str | None = None, keep_days: int = 90) -> int:
        from .date_storage import cleanup_snapshots

        snapshot_root = Path(snapshot_dir) if snapshot_dir else self.db_path.parent / "snapshots"
        return cleanup_snapshots(snapshot_root, keep_days=keep_days)


class PriceStorage:
    """DuckDB storage for normalized price pipeline output."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: duckdb.DuckDBPyConnection = duckdb.connect(str(self.db_path))
        self._ensure_tables()

    def close(self) -> None:
        self.conn.close()

    def _ensure_tables(self) -> None:
        _ = self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                brand TEXT,
                source_platform TEXT NOT NULL,
                product_url TEXT NOT NULL,
                image_url TEXT,
                attributes_json TEXT
            );
            CREATE TABLE IF NOT EXISTS price_snapshots (
                product_id TEXT NOT NULL,
                ts TIMESTAMP NOT NULL,
                price INTEGER NOT NULL,
                avg_price_30d INTEGER,
                avg_price_90d INTEGER,
                discount_rate_vs_avg DOUBLE,
                discount_rate_vs_list DOUBLE,
                source TEXT NOT NULL,
                meta_json TEXT
            );
            CREATE TABLE IF NOT EXISTS price_events (
                product_id TEXT NOT NULL,
                event_ts TIMESTAMP NOT NULL,
                event_type TEXT NOT NULL,
                drop_rate DOUBLE,
                saving_vs_avg INTEGER,
                radar_score DOUBLE NOT NULL,
                explanation TEXT NOT NULL
            );
            """
        )

    def upsert_products(self, products: Iterable[Product]) -> int:
        rows = [
            (
                product.id,
                product.title,
                product.category,
                product.brand,
                product.source_platform,
                product.product_url,
                product.image_url,
                json.dumps(product.attributes, ensure_ascii=False),
            )
            for product in products
        ]
        if not rows:
            return 0

        _ = self.conn.executemany(
            """
            INSERT INTO products (
                id, title, category, brand, source_platform, product_url, image_url, attributes_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = EXCLUDED.title,
                category = EXCLUDED.category,
                brand = EXCLUDED.brand,
                source_platform = EXCLUDED.source_platform,
                product_url = EXCLUDED.product_url,
                image_url = EXCLUDED.image_url,
                attributes_json = EXCLUDED.attributes_json
            """,
            rows,
        )
        return len(rows)

    def insert_snapshots(self, snapshots: Iterable[PriceSnapshot]) -> int:
        rows = [
            (
                snapshot.product_id,
                _utc_naive(snapshot.ts),
                snapshot.price,
                snapshot.avg_price_30d,
                snapshot.avg_price_90d,
                snapshot.discount_rate_vs_avg,
                snapshot.discount_rate_vs_list,
                snapshot.source,
                json.dumps(snapshot.meta, ensure_ascii=False),
            )
            for snapshot in snapshots
        ]
        if not rows:
            return 0

        _ = self.conn.executemany(
            """
            INSERT INTO price_snapshots (
                product_id, ts, price, avg_price_30d, avg_price_90d,
                discount_rate_vs_avg, discount_rate_vs_list, source, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)

    def insert_events(self, events: Iterable[PriceEvent]) -> int:
        rows = [
            (
                event.product_id,
                _utc_naive(event.event_ts),
                event.event_type,
                event.drop_rate,
                event.saving_vs_avg,
                event.radar_score,
                event.explanation,
            )
            for event in events
        ]
        if not rows:
            return 0

        _ = self.conn.executemany(
            """
            INSERT INTO price_events (
                product_id, event_ts, event_type, drop_rate,
                saving_vs_avg, radar_score, explanation
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)
