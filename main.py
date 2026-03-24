"""
PriceRadar 메인 실행 스크립트

사용법:
    python main.py --mode once              # 1회 실행
    python main.py --mode once --report     # 1회 실행 + 리포트 생성
    python main.py --mode scheduler         # 주기적 실행 (24시간 간격)
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from date_storage import apply_date_storage_policy
from priceradar.analyzers.price_scorer import PriceScorer
from priceradar.collectors.base import RawItem
from priceradar.collectors.registry import CollectorRegistry
from priceradar.config import load_notification_config
from priceradar.graph.graph_store import GraphStore
from priceradar.models import Article, CategoryConfig
from priceradar.notifier import PipelineNotifier, detect_price_notifications
from priceradar.raw_logger import RawLogger
from priceradar.reporter import generate_index_html
from priceradar.reporter import generate_report as generate_core_report
from priceradar.search_index import SearchIndex
from priceradar.validators import validate_article


def load_config(config_path: str = "config/config.yaml") -> dict[str, Any]:
    """설정 파일 로드"""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources(sources_path: str = "config/sources.yaml") -> dict[str, Any]:
    """소스 설정 파일 로드"""
    with open(sources_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_collection(
    config: dict[str, Any],
    sources_config: dict[str, Any],
    notifier: PipelineNotifier | None = None,
) -> None:
    """데이터 수집 실행"""
    print("\n=== 데이터 수집 시작 ===")
    start_time = time.time()

    db_path = config["database"]["path"]
    store = GraphStore(db_path)
    raw_logger = RawLogger(Path("data/raw"))
    search_index = SearchIndex(Path(os.getenv("PRICERADAR_SEARCH_DB_PATH", "data/search_index.db")))

    total_items_collected = 0
    total_items_saved = 0
    sources = sources_config.get("sources", [])

    # 중복 제거를 위한 URL 세트 (메모리 내)
    seen_urls = set()

    for source in sources:
        if not source.get("enabled", False):
            continue

        source_id = source.get("id")
        print(f"\n[{source_id}] 수집 중...")

        try:
            # 수집기 생성
            collector = CollectorRegistry.create_collector(source)

            # 데이터 수집
            items = collector.collect()
            total_items_collected += len(items)

            validated_items: list[RawItem] = []
            for item in items:
                is_valid, errors = validate_article(item)
                if not is_valid:
                    print(f"[{source_id}] invalid item skipped: {'; '.join(errors)}")
                    continue
                validated_items.append(item)

            unique_items: list[RawItem] = []
            for item in validated_items:
                if item.url and item.url in seen_urls:
                    continue
                unique_items.append(item)

            if notifier is not None and unique_items:
                product_ids = [item.product_id for item in unique_items if item.product_id]
                previous_states = _load_previous_product_states(store, product_ids)
                events = detect_price_notifications(
                    unique_items,
                    previous_states=previous_states,
                    rules=notifier.config.rules,
                )
                for event in events:
                    notifier.send(
                        title=event.title,
                        message=event.message,
                        priority=event.priority,
                        metadata=event.metadata,
                    )

            raw_logger.log(
                (_raw_item_to_article(item) for item in validated_items), source_name=source_id
            )

            # 중복 제거 후 저장
            saved_count = 0
            for item in unique_items:
                store.save_raw_item(item)
                search_index.upsert(
                    link=item.url,
                    title=item.title,
                    body=_build_search_body(item.platform, item.category, item.brand),
                )
                if item.url:
                    seen_urls.add(item.url)
                saved_count += 1
                total_items_saved += 1

            print(f"[{source_id}] {len(validated_items)}개 아이템 수집 완료")

        except Exception as e:
            print(f"[{source_id}] 수집 실패: {e}")
            continue

    store.close()

    elapsed = time.time() - start_time
    duplicates_removed = total_items_collected - total_items_saved
    print(f"\n수집 완료: 총 {total_items_collected}개 아이템 ({elapsed:.2f}초)")
    print(f"중복 제거: {duplicates_removed}개 (저장: {total_items_saved}개)")


def _raw_item_to_article(item: RawItem) -> Article:
    return Article(
        title=item.title,
        link=item.url,
        summary=f"Price item from {item.source}",
        published=item.collected_at,
        source=item.source,
        category=item.category or "price",
        matched_entities={},
        collected_at=item.collected_at,
    )


def _build_search_body(platform: str | None, category: str | None, brand: str | None) -> str:
    return " ".join(part for part in [platform, category, brand] if part)


def _load_previous_product_states(
    store: GraphStore,
    product_ids: list[str],
) -> dict[str, dict[str, Any]]:
    unique_ids = [product_id for product_id in set(product_ids) if product_id]
    if not unique_ids:
        return {}

    placeholders = ",".join("?" for _ in unique_ids)
    query = f"""
        SELECT
            product_id,
            MIN(CASE WHEN current_price > 0 THEN current_price END) AS min_price,
            arg_max(current_price, ts) AS last_price
        FROM price_snapshots
        WHERE product_id IN ({placeholders})
        GROUP BY product_id
    """

    rows = store.conn.execute(query, unique_ids).fetchall()
    return {
        str(product_id): {
            "min_price": float(min_price) if min_price is not None else None,
            "last_price": float(last_price) if last_price is not None else None,
        }
        for product_id, min_price, last_price in rows
    }


def run_scoring(config: dict[str, Any]) -> None:
    """가격 스코어링 실행"""
    print("\n=== 가격 스코어링 시작 ===")
    start_time = time.time()

    db_path = config["database"]["path"]
    store = GraphStore(db_path)

    # 스코어러 초기화
    scorer = PriceScorer(config.get("scoring", {}))

    # 모든 상품에 대해 스코어링 (최신 스냅샷 기준)
    # 간단한 구현: 최근 스냅샷을 조회하여 스코어 계산
    result = store.conn.execute(
        """
        SELECT DISTINCT p.product_id
        FROM products p
        INNER JOIN price_snapshots s ON p.product_id = s.product_id
    """
    ).fetchall()

    total_scored = 0

    for row in result:
        product_id = row[0]

        # 최신 스냅샷 조회
        snapshot = store.conn.execute(
            """
            SELECT current_price, avg_price, list_price, discount_rate,
                   is_lowest_now, is_popular, is_hotdeal
            FROM price_snapshots
            WHERE product_id = ?
            ORDER BY ts DESC
            LIMIT 1
        """,
            [product_id],
        ).fetchone()

        if not snapshot:
            continue

        # 가격 히스토리 조회 (최근 30개)
        history_rows = store.conn.execute(
            """
            SELECT current_price
            FROM price_snapshots
            WHERE product_id = ? AND current_price IS NOT NULL
            ORDER BY ts DESC
            LIMIT 30
        """,
            [product_id],
        ).fetchall()

        price_history = [row[0] for row in history_rows] if history_rows else None

        # 스코어 계산
        score = scorer.calculate_score(
            product_id=product_id,
            current_price=snapshot[0],
            avg_price=snapshot[1],
            list_price=snapshot[2],
            discount_rate=snapshot[3],
            is_lowest_now=snapshot[4],
            is_popular=snapshot[5],
            is_hotdeal=snapshot[6],
            price_history=price_history,
        )

        # 저장
        store.save_price_score(score)
        total_scored += 1

    store.close()

    elapsed = time.time() - start_time
    print(f"스코어링 완료: 총 {total_scored}개 상품 ({elapsed:.2f}초)")


def generate_report(config: dict[str, Any], output_dir: str | None = None) -> None:
    """HTML 리포트 생성"""
    print("\n=== 리포트 생성 시작 ===")

    db_path = config["database"]["path"]
    store = GraphStore(db_path)

    # 상위 딜 조회
    max_items = config.get("reporting", {}).get("max_items_per_report", 100)
    deals = store.get_top_deals(limit=max_items)

    print(f"상위 {len(deals)}개 딜 조회 완료")

    # 리포트 생성
    if output_dir is None:
        output_dir = str(config.get("reporting", {}).get("output_path", "reports"))

    os.makedirs(output_dir, exist_ok=True)
    report_date = datetime.now(tz=UTC).strftime("%Y%m%d")
    report_path = os.path.join(output_dir, f"price_{report_date}.html")

    articles: list[Article] = []
    for deal in deals:
        collected_at = deal.get("collected_at")
        published_at = collected_at if isinstance(collected_at, datetime) else None
        score = deal.get("radar_score")
        if isinstance(score, float | int):
            summary = f"Radar score {float(score):.2f}"
        else:
            summary = "Radar score unavailable"

        articles.append(
            Article(
                title=str(deal.get("title") or "Untitled deal"),
                link=str(deal.get("url") or ""),
                summary=str(deal.get("explanation") or summary),
                published=published_at,
                source=str(deal.get("platform") or deal.get("source") or "unknown"),
                category=str(deal.get("category") or "price"),
                matched_entities={},
                collected_at=published_at,
            )
        )

    category_config = CategoryConfig(
        category_name="price",
        display_name="Price Radar",
        sources=[],
        entities=[],
    )
    stats = {
        "sources": len({article.source for article in articles if article.source}),
        "collected": len(articles),
        "matched": 0,
        "window_days": 1,
    }
    generate_core_report(
        category=category_config,
        articles=articles,
        output_path=Path(report_path),
        stats=stats,
        errors=None,
        store=store,
    )

    # Generate unified index.html
    generate_index_html(Path(output_dir))

    store.close()

    print(f"리포트 생성 완료: {report_path}")


def run_once(
    config: dict[str, Any],
    sources_config: dict[str, Any],
    generate_report_flag: bool = False,
    notifier: PipelineNotifier | None = None,
    snapshot_db: bool = False,
) -> None:
    """1회 실행"""
    print("\n" + "=" * 60)
    print(f"PriceRadar 실행 시작: {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 데이터 수집
    run_collection(config, sources_config, notifier)

    # 2. 스코어링
    run_scoring(config)

    # 3. 리포트 생성 (옵션)
    if generate_report_flag:
        generate_report(config)

    # 4. Apply date storage policy
    if snapshot_db:
        try:
            db_path = config["database"]["path"]
            date_storage = apply_date_storage_policy(
                database_path=Path(db_path),
                raw_data_dir=Path("data") / "raw",
                report_dir=Path("reports"),
                keep_raw_days=180,
                keep_report_days=90,
                snapshot_db=snapshot_db,
            )
            snapshot_path = date_storage.get("snapshot_path")
            if isinstance(snapshot_path, str) and snapshot_path:
                print(f"Snapshot saved to {snapshot_path}")
        except Exception as e:
            print(f"Snapshot creation failed: {e}")

    # 5. 통계 출력
    db_path = config["database"]["path"]
    store = GraphStore(db_path)
    stats = store.get_stats()
    store.close()

    print("\n=== 통계 ===")
    print(f"총 상품 수: {stats['total_products']}")
    print(f"총 스냅샷 수: {stats['total_snapshots']}")
    print(f"총 스코어 수: {stats['total_scores']}")
    print("카테고리별 상품 수:")
    for category, count in stats["categories"].items():
        print(f"  - {category}: {count}")

    print("\n" + "=" * 60)
    print("PriceRadar 실행 완료")
    print("=" * 60 + "\n")


def run_scheduler(
    config: dict[str, Any],
    sources_config: dict[str, Any],
    interval_hours: int = 24,
    notifier: PipelineNotifier | None = None,
    snapshot_db: bool = False,
) -> None:
    """주기적 실행"""
    print(f"스케줄러 시작 ({interval_hours}시간 간격)")

    while True:
        run_once(
            config,
            sources_config,
            generate_report_flag=True,
            notifier=notifier,
            snapshot_db=snapshot_db,
        )

        print(f"\n다음 실행까지 {interval_hours}시간 대기 중...")
        time.sleep(interval_hours * 3600)


def main() -> None:
    """메인 함수"""
    parser = argparse.ArgumentParser(description="PriceRadar - 가격 추적 시스템")
    parser.add_argument(
        "--mode",
        choices=["once", "scheduler"],
        default="once",
        help="실행 모드 (once: 1회, scheduler: 주기적)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="리포트 생성 여부 (once 모드)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=24,
        help="스케줄러 실행 간격 (시간)",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="설정 파일 경로",
    )
    parser.add_argument(
        "--sources",
        default="config/sources.yaml",
        help="소스 설정 파일 경로",
    )
    parser.add_argument(
        "--notifications",
        default="config/notifications.yaml",
        help="알림 설정 파일 경로",
    )
    parser.add_argument(
        "--snapshot-db", action="store_true", default=False, help="Create database snapshot"
    )

    args = parser.parse_args()

    # 설정 로드
    config = load_config(args.config)
    sources_config = load_sources(args.sources)
    notification_config = load_notification_config(Path(args.notifications))
    notifier = PipelineNotifier(notification_config)

    # 모드별 실행
    if args.mode == "once":
        run_once(
            config,
            sources_config,
            generate_report_flag=args.report,
            notifier=notifier,
            snapshot_db=args.snapshot_db,
        )
    elif args.mode == "scheduler":
        run_scheduler(
            config,
            sources_config,
            interval_hours=args.interval,
            notifier=notifier,
            snapshot_db=args.snapshot_db,
        )


if __name__ == "__main__":
    main()
