"""
GraphStore - DuckDB 기반 데이터 저장 및 조회
"""

import os
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from priceradar.analyzers.price_scorer import PriceScore
from priceradar.collection_contract import infer_stock_status
from priceradar.collectors.base import RawItem
from priceradar.run_date import SNAPSHOT_KST_DATE_SQL, run_calendar_day


_PRICE_SNAPSHOT_CONTRACT_COLUMNS = {
    "discount_price": "INTEGER",
    "coupon_value": "INTEGER",
    "card_benefit": "INTEGER",
    "shipping_fee": "INTEGER",
    "effective_price": "INTEGER",
    "stock_status": "VARCHAR",
    "option_signature": "VARCHAR",
    "outlier_flag": "BOOLEAN",
}


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
        self.conn.execute("""
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
        """)

        # price_snapshots 테이블
        self.conn.execute("""
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
        """)
        self._ensure_price_snapshot_contract_columns()

        # price_scores 테이블
        self.conn.execute("""
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
        """)

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

    def _ensure_price_snapshot_contract_columns(self) -> None:
        existing_columns = {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info('price_snapshots')").fetchall()
        }
        for column_name, column_definition in _PRICE_SNAPSHOT_CONTRACT_COLUMNS.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(
                f"ALTER TABLE price_snapshots ADD COLUMN {column_name} {column_definition}"
            )
        self.conn.execute(
            "UPDATE price_snapshots SET outlier_flag = FALSE WHERE outlier_flag IS NULL"
        )

    def has_url_snapshot_on(self, url: str, snapshot_date: date) -> bool:
        """같은 URL이 해당 날짜에 가격 스냅샷을 이미 가지면 True."""
        normalized = url.strip()
        if not normalized:
            return False
        row = self.conn.execute(
            f"""
            SELECT 1
            FROM products p
            INNER JOIN price_snapshots s ON s.product_id = p.product_id
            WHERE p.url = ?
              AND {SNAPSHOT_KST_DATE_SQL} = ?
            LIMIT 1
            """,
            [normalized, snapshot_date],
        ).fetchone()
        return row is not None

    def urls_collected_on(self, snapshot_date: date) -> set[str]:
        """해당 날짜에 스냅샷이 있는 상품 URL."""
        rows = self.conn.execute(
            f"""
            SELECT DISTINCT p.url
            FROM products p
            INNER JOIN price_snapshots s ON s.product_id = p.product_id
            WHERE p.url IS NOT NULL
              AND {SNAPSHOT_KST_DATE_SQL} = ?
            """,
            [snapshot_date],
        ).fetchall()
        return {str(row[0]).strip() for row in rows if row[0] and str(row[0]).strip()}

    def save_raw_item(self, item: RawItem) -> bool:
        """RawItem을 저장 (products + price_snapshots).

        같은 URL이 같은 날에 이미 있으면 insert하지 않고 False를 반환한다.
        """
        url = item.url.strip()
        if url and self.has_url_snapshot_on(url, _snapshot_calendar_day(item.collected_at)):
            return False

        discount_price = _resolve_discount_price(item)
        effective_price = _resolve_effective_price(item, discount_price)
        stock_status = item.stock_status or infer_stock_status(
            item.title, item.current_price if item.current_price is not None else discount_price
        )

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
                url or item.url,
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
                source, is_hotdeal, is_popular, is_lowest_now, discount_price,
                coupon_value, card_benefit, shipping_fee, effective_price, stock_status,
                option_signature, outlier_flag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                discount_price,
                item.coupon_value,
                item.card_benefit,
                item.shipping_fee,
                effective_price,
                stock_status,
                item.option_signature,
                item.outlier_flag,
            ],
        )
        return True

    def save_price_score(self, score: PriceScore) -> None:
        """Keep one score per product. Daily runs must not append a new row."""
        self.conn.execute("DELETE FROM price_scores WHERE product_id = ?", [score.product_id])
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

    def backfill_contract_fields(self) -> int:
        """Fill effective price and stock from values already stored.

        Prices are copied from the observed current or discount price. Stock
        comes from an explicit sold-out title or from a positive price.
        Rows with no price stay null.
        """
        price_row = self.conn.execute("""
            SELECT COUNT(*) FROM price_snapshots
            WHERE (
                discount_price IS NULL
                AND current_price IS NOT NULL
                AND current_price > 0
            ) OR (
                effective_price IS NULL
                AND COALESCE(discount_price, current_price) IS NOT NULL
                AND COALESCE(discount_price, current_price) > 0
            )
            """).fetchone()
        self.conn.execute("""
            UPDATE price_snapshots
            SET discount_price = current_price
            WHERE discount_price IS NULL
              AND current_price IS NOT NULL
              AND current_price > 0
            """)
        self.conn.execute("""
            UPDATE price_snapshots
            SET effective_price = GREATEST(
                0,
                COALESCE(discount_price, current_price)
                    - COALESCE(coupon_value, 0)
                    - COALESCE(card_benefit, 0)
                    + COALESCE(shipping_fee, 0)
            )
            WHERE effective_price IS NULL
              AND COALESCE(discount_price, current_price) IS NOT NULL
              AND COALESCE(discount_price, current_price) > 0
            """)

        missing_stock = self.conn.execute("""
            SELECT s.snapshot_id, p.title, s.current_price, s.discount_price
            FROM price_snapshots s
            JOIN products p ON p.product_id = s.product_id
            WHERE s.stock_status IS NULL OR s.stock_status = ''
            """).fetchall()
        updates: list[tuple[str, int]] = []
        for snapshot_id, title, current_price, discount_price in missing_stock:
            observed_price = current_price if current_price is not None else discount_price
            status = infer_stock_status(
                str(title) if title is not None else None,
                int(observed_price) if observed_price is not None else None,
            )
            if status:
                updates.append((status, int(snapshot_id)))
        if updates:
            self.conn.executemany(
                "UPDATE price_snapshots SET stock_status = ? WHERE snapshot_id = ?",
                updates,
            )
        price_updates = int(price_row[0]) if price_row else 0
        return price_updates + len(updates)

    def retain_latest_price_scores(self) -> int:
        """Delete every score except the newest row for each product."""
        before_row = self.conn.execute("SELECT COUNT(*) FROM price_scores").fetchone()
        before = int(before_row[0]) if before_row else 0
        self.conn.execute("""
            CREATE TEMP TABLE IF NOT EXISTS keep_price_scores AS
            SELECT score_id FROM (
                SELECT
                    score_id,
                    row_number() OVER (
                        PARTITION BY product_id
                        ORDER BY ts DESC, score_id DESC
                    ) AS rn
                FROM price_scores
            )
            WHERE rn = 1
            """)
        self.conn.execute("DELETE FROM keep_price_scores")
        self.conn.execute("""
            INSERT INTO keep_price_scores
            SELECT score_id FROM (
                SELECT
                    score_id,
                    row_number() OVER (
                        PARTITION BY product_id
                        ORDER BY ts DESC, score_id DESC
                    ) AS rn
                FROM price_scores
            )
            WHERE rn = 1
            """)
        self.conn.execute("""
            DELETE FROM price_scores
            WHERE score_id NOT IN (SELECT score_id FROM keep_price_scores)
            """)
        self.conn.execute("DROP TABLE keep_price_scores")
        after_row = self.conn.execute("SELECT COUNT(*) FROM price_scores").fetchone()
        after = int(after_row[0]) if after_row else 0
        return max(0, before - after)

    def get_top_deals(self, limit: int = 20, category: str | None = None) -> list[dict[str, Any]]:
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
                snap.list_price,
                snap.discount_rate,
                snap.discount_price,
                snap.coupon_value,
                snap.card_benefit,
                snap.shipping_fee,
                snap.effective_price,
                snap.stock_status,
                snap.option_signature,
                snap.outlier_flag,
                snap.source,
                snap.collected_at
            FROM products p
            INNER JOIN (
                SELECT product_id, MAX(ts) as max_ts
                FROM price_scores
                GROUP BY product_id
            ) latest ON p.product_id = latest.product_id
            INNER JOIN price_scores s
                ON s.product_id = latest.product_id AND s.ts = latest.max_ts
            LEFT JOIN (
                SELECT
                    product_id,
                    ts AS collected_at,
                    current_price,
                    avg_price,
                    list_price,
                    discount_rate,
                    discount_price,
                    coupon_value,
                    card_benefit,
                    shipping_fee,
                    effective_price,
                    stock_status,
                    option_signature,
                    outlier_flag,
                    source
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
            params: list[Any] = [category]
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
            "list_price",
            "discount_rate",
            "discount_price",
            "coupon_value",
            "card_benefit",
            "shipping_fee",
            "effective_price",
            "stock_status",
            "option_signature",
            "outlier_flag",
            "source",
            "collected_at",
        ]

        return [dict(zip(columns, row, strict=False)) for row in result]

    def get_product(self, product_id: str) -> dict[str, Any] | None:
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
        products_row = self.conn.execute("SELECT COUNT(*) FROM products").fetchone()
        total_products = int(products_row[0]) if products_row else 0

        snapshots_row = self.conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()
        total_snapshots = int(snapshots_row[0]) if snapshots_row else 0

        scores_row = self.conn.execute("SELECT COUNT(*) FROM price_scores").fetchone()
        total_scores = int(scores_row[0]) if scores_row else 0

        categories = self.conn.execute("""
            SELECT category, COUNT(*) as count
            FROM products
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
        """).fetchall()

        return {
            "total_products": total_products,
            "total_snapshots": total_snapshots,
            "total_scores": total_scores,
            "categories": dict(categories),
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


def _is_duckdb_file(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 16:
        return False
    header = path.read_bytes()[:16]
    return b"DUCK" in header


def rewrite_duckdb_file(path: Path) -> int:
    """Copy the database into a new file so DELETE reclaims disk space."""
    export_dir = path.with_name(path.name + ".export")
    rewritten = path.with_name(path.name + ".rewrite")
    wal = Path(str(rewritten) + ".wal")
    for leftover in (rewritten, wal):
        if leftover.exists():
            leftover.unlink()
    if export_dir.exists():
        shutil.rmtree(export_dir)

    source = duckdb.connect(str(path))
    try:
        source.execute(f"EXPORT DATABASE '{export_dir.as_posix()}' (FORMAT PARQUET)")
        source.execute("CHECKPOINT")
    finally:
        source.close()

    output = duckdb.connect(str(rewritten))
    try:
        output.execute(f"IMPORT DATABASE '{export_dir.as_posix()}'")
        output.execute("CHECKPOINT")
    finally:
        output.close()

    os.replace(rewritten, path)
    if wal.exists():
        wal.unlink()
    if export_dir.exists():
        shutil.rmtree(export_dir)
    return path.stat().st_size


def prepare_price_database(database_path: Path) -> dict[str, object]:
    """Backfill contract fields and keep one price score per product.

    Compaction in radar-core refuses to empty a database whose newest row is
    already older than the age window. PriceRadar's score table grew by one
    row per product per run, so the file sits on GitHub's 100 MiB limit even
    though the price history itself is small. This trims scores first.
    """
    path = Path(database_path)
    if not _is_duckdb_file(path):
        return {
            "prepared": False,
            "reason": "not_duckdb",
            "scores_removed": 0,
            "rows_backfilled": 0,
            "bytes": path.stat().st_size if path.exists() else 0,
        }

    store = GraphStore(str(path))
    try:
        rows_backfilled = store.backfill_contract_fields()
        scores_removed = store.retain_latest_price_scores()
    finally:
        store.close()

    size = path.stat().st_size
    if scores_removed > 0:
        size = rewrite_duckdb_file(path)
    return {
        "prepared": True,
        "reason": "rewritten" if scores_removed > 0 else "updated",
        "scores_removed": scores_removed,
        "rows_backfilled": rows_backfilled,
        "bytes": size,
    }


def _snapshot_calendar_day(ts: datetime) -> date:
    """KST date of a collected instant. Naive values are UTC wall time."""
    return run_calendar_day(ts)


def _resolve_discount_price(item: RawItem) -> int | None:
    return item.discount_price if item.discount_price is not None else item.current_price


def _resolve_effective_price(item: RawItem, discount_price: int | None) -> int | None:
    if item.effective_price is not None:
        return item.effective_price
    if discount_price is None:
        return None

    effective_price = discount_price
    effective_price -= item.coupon_value or 0
    effective_price -= item.card_benefit or 0
    effective_price += item.shipping_fee or 0
    return max(0, effective_price)
