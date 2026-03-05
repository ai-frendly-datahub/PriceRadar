"""
GraphStore - DuckDB 기반 데이터 저장 및 조회
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import duckdb

from priceradar.analyzers.price_scorer import PriceScore
from priceradar.collectors.base import RawItem


class GraphStore:
    """DuckDB를 사용한 가격 데이터 저장소"""

    def __init__(self, db_path: str = "data/priceradar.duckdb") -> None:
        """
        Args:
            db_path: DuckDB 파일 경로
        """
        self.db_path = db_path

        # 데이터 디렉터리 생성
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        # DuckDB 연결
        self.conn = duckdb.connect(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        """테이블 스키마 초기화"""
        # 시퀀스 먼저 생성
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS snapshot_seq START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS score_seq START 1")

        # products 테이블
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_id VARCHAR PRIMARY KEY,
                title VARCHAR NOT NULL,
                url VARCHAR NOT NULL,
                category VARCHAR,
                brand VARCHAR,
                platform VARCHAR,
                image_url VARCHAR,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # price_snapshots 테이블
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_snapshots (
                snapshot_id INTEGER PRIMARY KEY DEFAULT nextval('snapshot_seq'),
                product_id VARCHAR NOT NULL,
                ts TIMESTAMP NOT NULL,
                current_price INTEGER,
                avg_price INTEGER,
                list_price INTEGER,
                discount_rate DOUBLE,
                source VARCHAR,
                is_hotdeal BOOLEAN DEFAULT FALSE,
                is_popular BOOLEAN DEFAULT FALSE,
                is_lowest_now BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            )
        """
        )

        # price_scores 테이블
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_scores (
                score_id INTEGER PRIMARY KEY DEFAULT nextval('score_seq'),
                product_id VARCHAR NOT NULL,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                radar_score DOUBLE NOT NULL,
                discount_strength DOUBLE,
                timing_rarity DOUBLE,
                popularity DOUBLE,
                volatility DOUBLE,
                saving_amount INTEGER,
                explanation VARCHAR,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            )
        """
        )

        # 인덱스 생성
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_product ON price_snapshots(product_id)"
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON price_snapshots(ts)")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scores_product ON price_scores(product_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scores_radar ON price_scores(radar_score)"
        )

    def save_raw_item(self, item: RawItem) -> None:
        """RawItem을 저장 (products + price_snapshots)"""
        # 1. products 테이블에 upsert
        self.conn.execute(
            """
            INSERT INTO products (
                product_id, title, url, category, brand, platform, image_url, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (product_id) DO UPDATE SET
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                category = EXCLUDED.category,
                brand = EXCLUDED.brand,
                platform = EXCLUDED.platform,
                image_url = EXCLUDED.image_url,
                last_updated = EXCLUDED.last_updated
        """,
            [
                item.product_id,
                item.title,
                item.url,
                item.category,
                item.brand,
                item.platform,
                item.image_url,
                item.collected_at,
            ],
        )

        # 2. price_snapshots 테이블에 insert
        self.conn.execute(
            """
            INSERT INTO price_snapshots (
                product_id, ts, current_price, avg_price, list_price, discount_rate,
                source, is_hotdeal, is_popular, is_lowest_now
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                item.product_id,
                item.collected_at,
                item.current_price,
                item.avg_price,
                item.list_price,
                item.discount_rate,
                item.source,
                item.is_hotdeal,
                item.is_popular,
                item.is_lowest_now,
            ],
        )

    def save_price_score(self, score: PriceScore) -> None:
        """PriceScore를 저장"""
        self.conn.execute(
            """
            INSERT INTO price_scores (
                product_id, radar_score, discount_strength, timing_rarity,
                popularity, volatility, saving_amount, explanation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                score.product_id,
                score.radar_score,
                score.discount_strength,
                score.timing_rarity,
                score.popularity,
                score.volatility,
                score.saving_amount,
                score.explanation,
            ],
        )

    def get_top_deals(
        self, limit: int = 20, category: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        레이다 점수 기준 상위 딜 조회

        Args:
            limit: 반환할 최대 개수
            category: 카테고리 필터 (선택)

        Returns:
            상품 정보 + 최신 스코어 리스트
        """
        query = """
            SELECT
                p.product_id,
                p.title,
                p.url,
                p.category,
                p.brand,
                p.platform,
                p.image_url,
                s.radar_score,
                s.discount_strength,
                s.timing_rarity,
                s.popularity,
                s.volatility,
                s.saving_amount,
                s.explanation,
                snap.current_price,
                snap.avg_price,
                snap.discount_rate
            FROM products p
            INNER JOIN (
                SELECT product_id, MAX(ts) as max_ts
                FROM price_scores
                GROUP BY product_id
            ) latest ON p.product_id = latest.product_id
            INNER JOIN price_scores s
                ON s.product_id = latest.product_id AND s.ts = latest.max_ts
            LEFT JOIN (
                SELECT product_id, current_price, avg_price, discount_rate
                FROM price_snapshots
                WHERE (product_id, ts) IN (
                    SELECT product_id, MAX(ts)
                    FROM price_snapshots
                    GROUP BY product_id
                )
            ) snap ON p.product_id = snap.product_id
        """

        if category:
            query += " WHERE p.category = ?"
            params = [category]
        else:
            params = []

        query += " ORDER BY s.radar_score DESC LIMIT ?"
        params.append(limit)

        result = self.conn.execute(query, params).fetchall()

        columns = [
            "product_id",
            "title",
            "url",
            "category",
            "brand",
            "platform",
            "image_url",
            "radar_score",
            "discount_strength",
            "timing_rarity",
            "popularity",
            "volatility",
            "saving_amount",
            "explanation",
            "current_price",
            "avg_price",
            "discount_rate",
        ]

        return [dict(zip(columns, row)) for row in result]

    def get_product(self, product_id: str) -> Optional[dict[str, Any]]:
        """특정 상품 정보 조회"""
        result = self.conn.execute(
            """
            SELECT product_id, title, url, category, brand, platform, image_url
            FROM products
            WHERE product_id = ?
        """,
            [product_id],
        ).fetchone()

        if not result:
            return None

        return {
            "product_id": result[0],
            "title": result[1],
            "url": result[2],
            "category": result[3],
            "brand": result[4],
            "platform": result[5],
            "image_url": result[6],
        }

    def get_recent_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        """최근 스냅샷 조회"""
        result = self.conn.execute(
            """
            SELECT product_id, ts, current_price, avg_price, discount_rate
            FROM price_snapshots
            ORDER BY ts DESC
            LIMIT ?
        """,
            [limit],
        ).fetchall()

        return [
            {
                "product_id": row[0],
                "ts": row[1],
                "current_price": row[2],
                "avg_price": row[3],
                "discount_rate": row[4],
            }
            for row in result
        ]

    def get_product_history(self, product_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """특정 상품의 가격 히스토리 조회"""
        result = self.conn.execute(
            """
            SELECT ts, current_price, avg_price, discount_rate, source
            FROM price_snapshots
            WHERE product_id = ?
            ORDER BY ts DESC
            LIMIT ?
        """,
            [product_id, limit],
        ).fetchall()

        return [
            {
                "ts": row[0],
                "current_price": row[1],
                "avg_price": row[2],
                "discount_rate": row[3],
                "source": row[4],
            }
            for row in result
        ]

    def get_stats(self) -> dict[str, Any]:
        """전체 통계 조회"""
        total_products = self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

        total_snapshots = self.conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]

        total_scores = self.conn.execute("SELECT COUNT(*) FROM price_scores").fetchone()[0]

        categories = self.conn.execute(
            """
            SELECT category, COUNT(*) as count
            FROM products
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
        """
        ).fetchall()

        return {
            "total_products": total_products,
            "total_snapshots": total_snapshots,
            "total_scores": total_scores,
            "categories": {cat: count for cat, count in categories},
        }

    def close(self) -> None:
        """DB 연결 종료"""
        if self.conn:
            self.conn.close()

    def __enter__(self) -> "GraphStore":
        """Context manager 진입"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager 종료"""
        self.close()
