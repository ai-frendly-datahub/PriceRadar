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
import re
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from priceradar.analyzers.price_scorer import PriceScorer
from priceradar.collection_contract import (
    EmptyCollectionError,
    EmptyOutputError,
    OversizedDatabaseError,
    emit_missing_secret_warning,
    ensure_collection_not_empty,
    ensure_database_within_limit,
    ensure_nonempty_files,
    is_challenge_or_error_page,
    missing_required_env,
)
from priceradar.collectors.base import RawItem
from priceradar.collectors.registry import CollectorRegistry
from priceradar.config import load_notification_config
from priceradar.date_storage import apply_date_storage_policy
from priceradar.exceptions import ChallengePageError
from priceradar.graph.graph_store import GraphStore
from priceradar.models import Article, CategoryConfig
from priceradar.notifier import PipelineNotifier, detect_price_notifications
from priceradar.pipeline import dedupe_by_url
from priceradar.quality_report import build_quality_report, write_quality_report
from priceradar.raw_logger import RawLogger
from priceradar.reporter import generate_index_html
from priceradar.reporter import generate_report as generate_core_report
from priceradar.run_date import run_calendar_day
from priceradar.search_index import SearchIndex
from priceradar.validators import validate_article


_PRICE_CATEGORY_SKIP = {"all", "기타", "misc", "unknown", "price"}
_PRICE_BRAND_STOPWORDS = {
    "국산",
    "더",
    "사은품",
    "산지",
    "신상",
    "오늘",
    "완숙",
    "정품",
    "추가",
    "최대",
    "최저가",
    "특가",
    "할인",
}


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
    *,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    """데이터 수집 실행"""
    print("\n=== 데이터 수집 시작 ===")
    start_time = time.time()
    moment = started_at or datetime.now(tz=UTC)
    run_date = run_calendar_day(moment)

    db_path = config["database"]["path"]
    store = GraphStore(db_path)
    raw_logger = RawLogger(Path("data/raw"), now=moment)
    search_index = SearchIndex(Path(os.getenv("PRICERADAR_SEARCH_DB_PATH", "data/search_index.db")))

    total_items_collected = 0
    total_items_saved = 0
    enabled_source_count = 0
    source_counts: dict[str, int] = {}
    sources = sources_config.get("sources", [])

    # 같은 KST 날짜에 이미 저장된 URL은 insert 전에 건너뛴다.
    seen_urls = store.urls_collected_on(run_date)

    for source in sources:
        if not source.get("enabled", False):
            continue

        source_id = str(source.get("id") or source.get("name") or "unknown")
        enabled_source_count += 1
        missing_env = missing_required_env(source)
        if missing_env:
            emit_missing_secret_warning(source_id, missing_env)
            raw_logger.log_skip(source_name=source_id, required_env=missing_env)
            source_counts[source_id] = 0
            print(f"\n[{source_id}] skipped; required env {', '.join(missing_env)}")
            continue

        print(f"\n[{source_id}] 수집 중...")

        try:
            # 수집기 생성
            collector = CollectorRegistry.create_collector(source)

            # 데이터 수집. 챌린지/쿠키월 문서는 저장하지 않는다.
            items = [
                item
                for item in collector.collect()
                if not is_challenge_or_error_page(item.title, item.title)
            ]
            total_items_collected += len(items)
            source_counts[source_id] = len(items)

            validated_items: list[RawItem] = []
            for item in items:
                is_valid, errors = validate_article(item)
                if not is_valid:
                    print(f"[{source_id}] invalid item skipped: {'; '.join(errors)}")
                    continue
                validated_items.append(item)

            unique_items = dedupe_by_url(validated_items, seen_urls)

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
                (_raw_item_to_article(item) for item in unique_items), source_name=source_id
            )

            # 중복 제거 후 저장
            for item in unique_items:
                if not store.save_raw_item(item):
                    continue
                search_index.upsert(
                    link=item.url,
                    title=item.title,
                    body=_build_search_body(item.platform, item.category, item.brand),
                )
                total_items_saved += 1

            print(f"[{source_id}] {len(validated_items)}개 아이템 수집 완료")

        except ChallengePageError as e:
            source_counts[source_id] = 0
            print(f"[{source_id}] 챌린지 페이지라 건너뜀: {e}")
            continue
        except Exception as e:
            source_counts.setdefault(source_id, 0)
            print(f"[{source_id}] 수집 실패: {e}")
            continue

    store.close()

    elapsed = time.time() - start_time
    duplicates_removed = total_items_collected - total_items_saved
    print(f"\n수집 완료: 총 {total_items_collected}개 아이템 ({elapsed:.2f}초)")
    print(f"중복 제거: {duplicates_removed}개 (저장: {total_items_saved}개)")
    for source_id, count in source_counts.items():
        print(f"  - {source_id}: {count}")
    ensure_collection_not_empty(
        collected_count=total_items_collected,
        enabled_source_count=enabled_source_count,
    )
    return {
        "enabled_source_count": enabled_source_count,
        "collected": total_items_collected,
        "saved": total_items_saved,
        "sources": source_counts,
    }


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


def _clean_entity_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"none", "null", "n/a", "unknown"}:
        return None
    return text


def _add_entity(matches: dict[str, list[str]], namespace: str, value: str) -> None:
    matches[f"{namespace}:{value}"] = [value]


def _deal_source(deal: dict[str, Any]) -> str:
    return (
        _clean_entity_value(deal.get("source"))
        or _clean_entity_value(deal.get("platform"))
        or "unknown"
    )


def _extract_brand_candidate(title: Any, explicit_brand: Any = None) -> str | None:
    explicit = _clean_entity_value(explicit_brand)
    if explicit:
        return explicit

    raw_title = _clean_entity_value(title)
    if raw_title is None:
        return None

    title_without_prefix = re.sub(r"^\([^)]*\)\s*", "", raw_title)
    title_without_prefix = re.sub(r"^\[[^\]]*\]\s*", "", title_without_prefix)
    candidate = re.split(r"[\s,\[\](/]+", title_without_prefix, maxsplit=1)[0]
    candidate = candidate.strip("·-_:;~!\"'")
    if len(candidate) < 2:
        return None
    if candidate.lower() in _PRICE_BRAND_STOPWORDS:
        return None
    if candidate.isdigit():
        return None
    return candidate


def _discount_bucket(discount_rate: Any) -> str | None:
    if not isinstance(discount_rate, (int, float)):
        return None
    if discount_rate >= 0.7:
        return "70%+"
    if discount_rate >= 0.5:
        return "50%+"
    if discount_rate >= 0.3:
        return "30%+"
    if discount_rate > 0:
        return "discounted"
    return None


def _price_band(price: Any) -> str | None:
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    if price < 10_000:
        return "under_10k"
    if price < 50_000:
        return "10k_50k"
    if price < 200_000:
        return "50k_200k"
    return "200k_plus"


def _deal_matched_entities(deal: dict[str, Any]) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}

    category = _clean_entity_value(deal.get("category"))
    if category and category.lower() not in _PRICE_CATEGORY_SKIP:
        _add_entity(matches, "category", category)

    platform = _clean_entity_value(deal.get("platform"))
    if platform:
        _add_entity(matches, "platform", platform)

    source = _clean_entity_value(deal.get("source"))
    if source:
        _add_entity(matches, "source", source)

    brand = _extract_brand_candidate(deal.get("title"), deal.get("brand"))
    if brand:
        _add_entity(matches, "brand", brand)

    discount = _discount_bucket(deal.get("discount_rate"))
    if discount:
        _add_entity(matches, "discount", discount)

    band = _price_band(deal.get("current_price"))
    if band:
        _add_entity(matches, "price_band", band)

    return matches


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
    result = store.conn.execute("""
        SELECT DISTINCT p.product_id
        FROM products p
        INNER JOIN price_snapshots s ON p.product_id = s.product_id
    """).fetchall()

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


def generate_report(
    config: dict[str, Any],
    output_dir: str | None = None,
    quality_report: dict[str, Any] | None = None,
    *,
    report_date: date | None = None,
) -> None:
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
    dated = report_date or run_calendar_day()
    report_stamp = dated.strftime("%Y%m%d")
    report_path = os.path.join(output_dir, f"price_{report_stamp}.html")

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
                source=_deal_source(deal),
                category=str(deal.get("category") or "price"),
                matched_entities=_deal_matched_entities(deal),
                collected_at=published_at,
            )
        )

    category_config = CategoryConfig(
        category_name="price",
        display_name="Price Radar",
        sources=[],
        entities=[],
    )
    matched_count = sum(1 for article in articles if article.matched_entities)
    source_count = len({article.source for article in articles if article.source})
    stats = {
        "sources": source_count,
        "collected": len(articles),
        "matched": matched_count,
        "window_days": 1,
        "article_count": len(articles),
        "source_count": source_count,
        "matched_count": matched_count,
    }
    generate_core_report(
        category=category_config,
        articles=articles,
        output_path=Path(report_path),
        stats=stats,
        errors=None,
        store=store,
        quality_report=quality_report,
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
    keep_raw_days: int = 180,
    keep_report_days: int = 90,
    keep_snapshot_days: int = 30,
    *,
    started_at: datetime | None = None,
) -> None:
    """1회 실행"""
    print("\n" + "=" * 60)
    moment = started_at or datetime.now(tz=UTC)
    run_date = run_calendar_day(moment)
    print(f"PriceRadar 실행 시작: {moment.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"수집 기준일(KST): {run_date.isoformat()}")
    print("=" * 60)

    # 1. 데이터 수집
    run_collection(config, sources_config, notifier, started_at=moment)

    # 2. 스코어링
    run_scoring(config)

    # 3. Data quality contract report
    quality_report: dict[str, Any] | None = None
    try:
        report_dir = Path(config.get("reporting", {}).get("output_path", "reports"))
        target_date = run_date
        max_items = config.get("reporting", {}).get("max_items_per_report", 100)
        db_path = config["database"]["path"]
        quality_store = GraphStore(db_path)
        try:
            quality_deals = quality_store.get_top_deals(limit=max_items)
        finally:
            quality_store.close()
        quality_report = build_quality_report(
            sources_config,
            target_date=target_date,
            deal_rows=quality_deals,
        )
        quality_paths = write_quality_report(
            quality_report,
            report_dir,
            target_date=target_date,
        )
        print(f"Data quality report saved to {quality_paths['latest']}")
    except Exception as e:
        print(f"Data quality report generation failed: {e}")

    # 4. 리포트 생성 (옵션)
    if generate_report_flag:
        generate_report(config, quality_report=quality_report, report_date=run_date)

    # 5. Apply date storage policy
    try:
        db_path = config["database"]["path"]
        date_storage = apply_date_storage_policy(
            database_path=Path(db_path),
            raw_data_dir=Path("data") / "raw",
            report_dir=Path("reports"),
            keep_raw_days=keep_raw_days,
            keep_report_days=keep_report_days,
            keep_snapshot_days=keep_snapshot_days,
            snapshot_db=snapshot_db,
            today=run_date,
        )
        snapshot_path = date_storage.get("snapshot_path")
        if isinstance(snapshot_path, str) and snapshot_path:
            print(f"Snapshot saved to {snapshot_path}")
        print(
            "DuckDB compaction: "
            f"compacted={date_storage.get('db_compacted')} "
            f"reason={date_storage.get('db_reason')} "
            f"bytes={date_storage.get('db_bytes_before')} -> {date_storage.get('db_bytes')} "
            f"rows_deleted={date_storage.get('db_rows_deleted')} "
            f"scores_removed={date_storage.get('scores_removed')} "
            f"rows_backfilled={date_storage.get('rows_backfilled')}"
        )
    except Exception as e:
        print(f"Date storage policy failed: {e}")

    database_path = Path(config["database"]["path"])
    ensure_database_within_limit(database_path)
    report_dir = Path(config.get("reporting", {}).get("output_path", "reports"))
    if generate_report_flag and report_dir.exists():
        produced = [
            path
            for path in report_dir.iterdir()
            if path.is_file() and path.suffix in {".html", ".json"} and "price_" in path.name
        ]
        ensure_nonempty_files(produced)
        for snapshot in database_path.parent.rglob("*.duckdb"):
            ensure_database_within_limit(snapshot)

    # 6. 통계 출력
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
    keep_raw_days: int = 180,
    keep_report_days: int = 90,
    keep_snapshot_days: int = 30,
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
            keep_raw_days=keep_raw_days,
            keep_report_days=keep_report_days,
            keep_snapshot_days=keep_snapshot_days,
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
    parser.add_argument(
        "--keep-raw-days", type=int, default=180, help="Retention window for raw JSONL directories"
    )
    parser.add_argument(
        "--keep-report-days", type=int, default=90, help="Retention window for dated HTML reports"
    )
    parser.add_argument(
        "--keep-snapshot-days",
        type=int,
        default=30,
        help="Retention window for dated DuckDB snapshots",
    )

    args = parser.parse_args()

    # 설정 로드
    config = load_config(args.config)
    sources_config = load_sources(args.sources)
    notification_config = load_notification_config(Path(args.notifications))
    notifier = PipelineNotifier(notification_config)

    # 모드별 실행
    try:
        if args.mode == "once":
            run_once(
                config,
                sources_config,
                generate_report_flag=args.report,
                notifier=notifier,
                snapshot_db=args.snapshot_db,
                keep_raw_days=args.keep_raw_days,
                keep_report_days=args.keep_report_days,
                keep_snapshot_days=args.keep_snapshot_days,
            )
        elif args.mode == "scheduler":
            run_scheduler(
                config,
                sources_config,
                interval_hours=args.interval,
                notifier=notifier,
                snapshot_db=args.snapshot_db,
                keep_raw_days=args.keep_raw_days,
                keep_report_days=args.keep_report_days,
                keep_snapshot_days=args.keep_snapshot_days,
            )
    except EmptyCollectionError as exc:
        print(f"::error title=PriceRadar empty collection::{exc}", flush=True)
        raise SystemExit(1) from exc
    except (OversizedDatabaseError, EmptyOutputError) as exc:
        print(f"::error title=PriceRadar output rejected::{exc}", flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
