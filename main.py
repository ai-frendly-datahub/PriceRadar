"""
PriceRadar 메인 실행 스크립트

사용법:
    python main.py --mode once              # 1회 실행
    python main.py --mode once --report     # 1회 실행 + 리포트 생성
    python main.py --mode scheduler         # 주기적 실행 (24시간 간격)
"""

import argparse
import os
import time
from datetime import datetime
from pathlib import Path

import yaml

from priceradar.analyzers.price_scorer import PriceScorer
from priceradar.collectors.registry import CollectorRegistry
from priceradar.graph.graph_store import GraphStore
from priceradar.reporters.html_reporter import HtmlReporter


def load_config(config_path: str = "config/config.yaml") -> dict:
    """설정 파일 로드"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources(sources_path: str = "config/sources.yaml") -> dict:
    """소스 설정 파일 로드"""
    with open(sources_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_collection(config: dict, sources_config: dict) -> None:
    """데이터 수집 실행"""
    print("\n=== 데이터 수집 시작 ===")
    start_time = time.time()

    db_path = config["database"]["path"]
    store = GraphStore(db_path)

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

            # 중복 제거 후 저장
            saved_count = 0
            for item in items:
                # URL 기준 중복 확인
                if item.url and item.url in seen_urls:
                    continue

                store.save_raw_item(item)
                if item.url:
                    seen_urls.add(item.url)
                saved_count += 1
                total_items_saved += 1

            print(f"[{source_id}] {len(items)}개 아이템 수집 완료")

        except Exception as e:
            print(f"[{source_id}] 수집 실패: {e}")
            continue

    store.close()

    elapsed = time.time() - start_time
    duplicates_removed = total_items_collected - total_items_saved
    print(f"\n수집 완료: 총 {total_items_collected}개 아이템 ({elapsed:.2f}초)")
    print(f"중복 제거: {duplicates_removed}개 (저장: {total_items_saved}개)")


def run_scoring(config: dict) -> None:
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


def generate_report(config: dict, output_dir: str = None) -> None:
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
        output_dir = config.get("reporting", {}).get("output_path", "docs/reports")

    today = datetime.now().strftime("%Y-%m-%d")
    report_dir = os.path.join(output_dir, today)
    os.makedirs(report_dir, exist_ok=True)

    report_path = os.path.join(report_dir, "index.html")

    reporter = HtmlReporter()
    reporter.generate_report(
        deals=deals,
        output_path=report_path,
        title=f"PriceRadar 일일 리포트 - {today}",
    )

    store.close()

    print(f"리포트 생성 완료: {report_path}")


def run_once(config: dict, sources_config: dict, generate_report_flag: bool = False) -> None:
    """1회 실행"""
    print("\n" + "=" * 60)
    print(f"PriceRadar 실행 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 데이터 수집
    run_collection(config, sources_config)

    # 2. 스코어링
    run_scoring(config)

    # 3. 리포트 생성 (옵션)
    if generate_report_flag:
        generate_report(config)

    # 4. 통계 출력
    db_path = config["database"]["path"]
    store = GraphStore(db_path)
    stats = store.get_stats()
    store.close()

    print("\n=== 통계 ===")
    print(f"총 상품 수: {stats['total_products']}")
    print(f"총 스냅샷 수: {stats['total_snapshots']}")
    print(f"총 스코어 수: {stats['total_scores']}")
    print(f"카테고리별 상품 수:")
    for category, count in stats["categories"].items():
        print(f"  - {category}: {count}")

    print("\n" + "=" * 60)
    print("PriceRadar 실행 완료")
    print("=" * 60 + "\n")


def run_scheduler(config: dict, sources_config: dict, interval_hours: int = 24) -> None:
    """주기적 실행"""
    print(f"스케줄러 시작 ({interval_hours}시간 간격)")

    while True:
        run_once(config, sources_config, generate_report_flag=True)

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

    args = parser.parse_args()

    # 설정 로드
    config = load_config(args.config)
    sources_config = load_sources(args.sources)

    # 모드별 실행
    if args.mode == "once":
        run_once(config, sources_config, generate_report_flag=args.report)
    elif args.mode == "scheduler":
        run_scheduler(config, sources_config, interval_hours=args.interval)


if __name__ == "__main__":
    main()
