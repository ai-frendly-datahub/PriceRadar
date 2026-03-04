"""
PriceRadar 데모 파이프라인

간단한 데이터 흐름을 보여주는 데모 스크립트
"""

from datetime import datetime

from priceradar.analyzers.price_scorer import PriceScorer
from priceradar.collectors.base import RawItem
from priceradar.graph.graph_store import GraphStore
from priceradar.reporters.html_reporter import HtmlReporter


def create_sample_items() -> list[RawItem]:
    """샘플 데이터 생성"""
    items = [
        RawItem(
            product_id="demo_001",
            title="삼성전자 갤럭시북4 프로 16GB",
            url="https://example.com/product1",
            source="demo_source",
            current_price=1890000,
            avg_price=2100000,
            list_price=2300000,
            discount_rate=0.25,
            category="electronics",
            platform="coupang",
            is_lowest_now=True,
            is_popular=True,
        ),
        RawItem(
            product_id="demo_002",
            title="다이슨 V15 무선청소기",
            url="https://example.com/product2",
            source="demo_source",
            current_price=580000,
            avg_price=650000,
            list_price=890000,
            discount_rate=0.35,
            category="living",
            platform="coupang",
            is_hotdeal=True,
        ),
        RawItem(
            product_id="demo_003",
            title="Apple AirPods Pro 2세대",
            url="https://example.com/product3",
            source="demo_source",
            current_price=289000,
            avg_price=320000,
            list_price=359000,
            discount_rate=0.20,
            category="electronics",
            platform="naver",
            is_popular=True,
        ),
        RawItem(
            product_id="demo_004",
            title="LG 트롬 건조기 듀얼인버터",
            url="https://example.com/product4",
            source="demo_source",
            current_price=1250000,
            avg_price=1400000,
            list_price=1600000,
            discount_rate=0.22,
            category="living",
            platform="coupang",
            is_lowest_now=True,
        ),
        RawItem(
            product_id="demo_005",
            title="에스티로더 어드밴스드 나이트 리페어",
            url="https://example.com/product5",
            source="demo_source",
            current_price=89000,
            avg_price=110000,
            list_price=125000,
            discount_rate=0.29,
            category="beauty",
            platform="oliveyoung",
            is_hotdeal=True,
            is_popular=True,
        ),
    ]
    return items


def main() -> None:
    """데모 파이프라인 실행"""
    print("=" * 60)
    print("PriceRadar 데모 파이프라인")
    print("=" * 60 + "\n")

    # 1. 샘플 데이터 생성
    print("1. 샘플 데이터 생성 중...")
    items = create_sample_items()
    print(f"   → {len(items)}개 상품 생성 완료\n")

    # 2. 데이터 저장
    print("2. 데이터베이스 저장 중...")
    store = GraphStore("data/demo.duckdb")

    for item in items:
        store.save_raw_item(item)
        print(f"   → {item.title[:30]}... 저장 완료")

    print()

    # 3. 스코어링
    print("3. 가격 스코어링 중...")
    scorer = PriceScorer(
        {
            "discount_strength": 0.4,
            "timing_rarity": 0.3,
            "popularity": 0.2,
            "volatility_penalty": 0.1,
        }
    )

    for item in items:
        score = scorer.calculate_score(
            product_id=item.product_id,
            current_price=item.current_price,
            avg_price=item.avg_price,
            list_price=item.list_price,
            discount_rate=item.discount_rate,
            is_lowest_now=item.is_lowest_now,
            is_popular=item.is_popular,
            is_hotdeal=item.is_hotdeal,
        )
        store.save_price_score(score)
        print(
            f"   → {item.title[:30]}... 점수: {score.radar_score:.2f}"
        )

    print()

    # 4. 상위 딜 조회
    print("4. 상위 딜 조회 중...")
    deals = store.get_top_deals(limit=10)

    print(f"   → 상위 {len(deals)}개 딜:\n")
    for i, deal in enumerate(deals, 1):
        print(f"   {i}. {deal['title'][:40]}")
        print(f"      가격: {deal['current_price']:,}원 (점수: {deal['radar_score']:.2f})")
        print(f"      {deal['explanation']}\n")

    # 5. HTML 리포트 생성
    print("5. HTML 리포트 생성 중...")
    reporter = HtmlReporter()
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = f"docs/reports/demo/index.html"

    reporter.generate_report(
        deals=deals,
        output_path=report_path,
        title=f"PriceRadar 데모 리포트 - {today}",
    )

    print(f"   → 리포트 생성 완료: {report_path}\n")

    # 6. 통계 출력
    print("6. 통계 정보")
    stats = store.get_stats()
    print(f"   → 총 상품 수: {stats['total_products']}")
    print(f"   → 총 스냅샷 수: {stats['total_snapshots']}")
    print(f"   → 총 스코어 수: {stats['total_scores']}")
    print(f"   → 카테고리별 상품 수:")
    for category, count in stats["categories"].items():
        print(f"      - {category}: {count}")

    store.close()

    print("\n" + "=" * 60)
    print("데모 파이프라인 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
