# PriceRadar

**🌐 Live Report**: https://ai-frendly-datahub.github.io/PriceRadar/


[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

여러 쇼핑몰의 가격 변동과 딜 정보를 수집·분석하여, **지금 사야 할 상품**을 레이다 형태로 제공하는 가격 추적 시스템입니다.

폴센트(Fallcent) 같은 가격 추적 서비스를 데이터 소스로 활용하며, 관심라이더(InterestRadar) 체계에서 "가격 축"을 담당하도록 설계되었습니다.

## 프로젝트 목표

- **가격 변동 실시간 추적**: 여러 쇼핑몰의 상품 가격과 할인 정보를 일일 자동 수집·저장
- **최적 구매 시점 추천**: 할인 강도, 타이밍 희소성, 인기도, 가격 안정성의 4축 스코어링으로 구매 타이밍 제안
- **카테고리 자동 분류**: 16개 상품 카테고리 자동 탐지로 분야별 가격 트렌드 분석
- **소비자 의사결정 지원**: "지금 사야 할 상품"을 한눈에 보여주는 인터랙티브 HTML 리포트
- **AI 가격 도구**: MCP 서버를 통해 AI 어시스턴트에서 가격 추적 및 할인 알림 도구 직접 활용

## 주요 기능

1. **자동 가격 수집**: 폴센트, 에누리 등의 소스에서 상품 가격 정보를 자동으로 수집합니다.
2. **4축 스코어링**: 할인 강도, 타이밍 희소성, 인기도, 가격 안정성 4가지 축으로 구매 타이밍을 점수화합니다.
3. **DuckDB 저장**: 가격 히스토리와 스코어를 DuckDB에 저장하여 시계열 분석을 지원합니다.
4. **인터랙티브 리포트**: 카테고리/플랫폼 필터, 정렬 기능이 있는 HTML 리포트를 자동 생성합니다.
5. **카테고리 자동 분류**: 16개 카테고리를 자동으로 탐지하여 분류합니다.
6. **GitHub Actions 자동화**: 매일 자동으로 가격을 수집하고 리포트를 생성합니다.
7. **GitHub Pages 배포**: 최신 리포트를 자동으로 웹에 배포합니다.

## 빠른 시작

### 사전 요구사항

- Python 3.11 이상
- Git

### 로컬 실행

```bash
git clone https://github.com/<username>/PriceRadar.git
cd PriceRadar

# 가상환경 생성 및 의존성 설치
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 데모 파이프라인 실행 (샘플 데이터)
python demo_pipeline.py

# 1회 수집 실행 (리포트 생성 포함)
python main.py --mode once --report

# 정기 수집 스케줄러 실행 (24시간 간격)
python main.py --mode scheduler --interval 24
```

### 환경 변수

- `PRICERADAR_DB_PATH`: DuckDB 파일 경로. 기본값은 `data/priceradar.duckdb`.

### 데이터 품질 리포트

`config/sources.yaml`의 `data_quality` 계약은 SKU key, 실구매가 구성요소, 재고 전환, 공식 스토어 후보를 매일 점검한다. `python -m priceradar.quality_report --sources config/sources.yaml --output-dir reports`를 실행하면 `reports/price_quality.json`과 `reports/price_YYYYMMDD_quality.json`이 생성된다.

## 프로젝트 구조

```
PriceRadar/
├── priceradar/
│   ├── collectors/      # 데이터 수집기 (HTML 파싱 등)
│   ├── analyzers/       # 가격 분석 및 스코어링
│   ├── graph/           # DuckDB 기반 데이터 저장소
│   ├── reporters/       # HTML 리포트 생성
│   ├── pushers/         # 알림 채널 (확장 가능)
│   └── mcp_server/      # MCP 서버 (선택적)
├── config/              # 설정 파일 (소스, 가중치 등)
├── docs/                # 문서 (아키텍처, PRD 등)
├── tests/               # 테스트 (unit/integration/e2e)
├── main.py              # 메인 실행 스크립트
└── demo_pipeline.py     # 데모 파이프라인
```

## 핵심 개념

### 가격 레이다 스코어링

PriceRadar는 4가지 축으로 상품의 구매 타이밍을 점수화합니다:

```python
radar_score =
  0.4 * discount_strength +    # 할인 강도
  0.3 * timing_rarity +         # 타이밍 희소성
  0.2 * popularity +            # 인기도
  0.1 * (1 - volatility)        # 가격 안정성
```

1. **할인 강도 (40%)**: 현재가 vs 평균가/정가 비교
2. **타이밍 희소성 (30%)**: 90일 내 최저가 여부, 가격 히스토리 분석
3. **인기도 (20%)**: 인기 상품, 핫딜 태그
4. **가격 안정성 (10%)**: 가격 변동성 (낮을수록 좋음)

### 데이터 모델

#### Product (상품)
```python
{
  "product_id": "fallcent_main_abc123",
  "title": "삼성전자 갤럭시북4 프로",
  "url": "https://coupang.com/...",
  "category": "electronics",
  "platform": "coupang"
}
```

#### PriceSnapshot (가격 스냅샷)
```python
{
  "product_id": "fallcent_main_abc123",
  "ts": "2025-11-24T09:00:00",
  "current_price": 1890000,
  "avg_price": 2100000,
  "discount_rate": 0.25,
  "is_lowest_now": True
}
```

#### PriceScore (레이다 점수)
```python
{
  "product_id": "fallcent_main_abc123",
  "radar_score": 0.85,
  "discount_strength": 0.90,
  "timing_rarity": 1.00,
  "popularity": 0.50,
  "explanation": "현재 최저가입니다. 평균보다 210,000원 저렴합니다."
}
```

## 문서

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - 시스템 아키텍처 및 모듈 구조
- [PRD.md](docs/PRD.md) - 제품 요구사항 정의
- [DATA_SOURCES.md](docs/DATA_SOURCES.md) - 데이터 소스 전략 및 우선순위
- [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) - 구현 상태 및 실행 결과
- [ROADMAP.md](docs/ROADMAP.md) - 개발 로드맵

## 기술 스택

- **언어**: Python 3.11+
- **데이터 저장소**: DuckDB (파일 기반)
- **수집/파싱**: `requests`, `beautifulsoup4`
- **템플릿**: `jinja2`
- **테스트**: `pytest`

## 개발 상태

### ✅ 완료 (2025-11-24 업데이트)
- [x] **폴센트 Collector** - 85개 상품 수집 (16개 카테고리 자동 분류)
- [x] **에누리 Collector** - 46개 상품 수집 (JavaScript 파싱)
- [x] **카테고리 자동 탐지** - 95% 정확도 (electronics, food, living 등)
- [x] **중복 제거 로직** - URL 기반 (97% 효율)
- [x] **가격 스코어링** - 293개 상품 분석
- [x] **DuckDB 저장소** - 830개 스냅샷 저장
- [x] **HTML 리포트 생성** - 일일 딜 리포트
- [x] **데이터 소스 리서치** - 한국 가격 추적 서비스 4곳 분석

### 📊 최신 실행 결과 (2025-11-24 15:58)

```bash
python main.py --mode once --report
```

**수집 성과**:
- 총 131개 아이템 수집 (5.5초)
- 중복 제거: 6개 (저장: 125개)
- 293개 상품 스코어링 완료
- 상위 딜: 5,010원 ~ 23,220원 (할인율 9~61%)

**활성 소스**:
- ✅ 폴센트 메인 (85개) - 16개 카테고리 전체
- ✅ 에누리 메인 (46개) - 인기 상품

**플랫폼 분포**:
- 쿠팡 (coupang): 152개
- 11번가 (elevenst): 13개
- G마켓 (gmarket): 11개
- 기타: 미확인 22개

**카테고리 분포** (15개):
- electronics: 83개
- all: 56개
- furniture, beauty, food, accessories, living, sports, fashion: 10-17개
- pet, toys, kitchen, baby, automotive, office: 5-11개

**상위 5개 딜**:
1. 페어리 맥스 무균 밀폐용기 - 5,010원 (점수 0.90, 61% 할인)
2. 롬앤 틴트 - 5,900원 (점수 0.88, 47% 할인)
3. SD7 실리콘 수모 - 8,800원 (점수 0.87, 46% 할인)
4. 요즘 그릭요거트 - 7,700원 (점수 0.85, 44% 할인)
5. 솔본 솔잎비누 - 23,220원 (점수 0.79, 15% 할인)

### 🚧 다음 단계
- [ ] 다나와/역대가 Collector 추가
- [ ] GitHub Actions 자동화 (매일 자동 수집)
- [ ] 리포트 개선 (카테고리 필터, 가격 추이 그래프)
- [ ] 알림 기능 (텔레그램, 이메일)

## 향후 확장

### Phase 2
- [ ] 사용자별 개인화 (관심 카테고리, 가격대)
- [ ] 가격 예측 (머신러닝 기반)
- [ ] MCP 서버 (Claude Desktop 연동)

### Phase 3
- [ ] 다른 라이더와 통합 (TrendRadar, WineRadar)
- [ ] 공통 RadarItem 인터페이스
- [ ] 교차 필터링 (트렌드 + 가격)

## 기여 가이드

1. 이슈를 만들거나 기존 이슈에 의견을 남깁니다.
2. Fork + 브랜치 생성 후 작업합니다.
3. `pytest`로 테스트를 통과시킵니다.
4. Pull Request를 제출합니다.

## 라이선스

MIT License – 자세한 내용은 [LICENSE](LICENSE)를 참고하세요.

<!-- DATAHUB-OPS-AUDIT:START -->
## DataHub Operations

- CI/CD workflows: `daily-collection.yml`, `pr-checks.yml`, `radar-crawler.yml`, `release.yml`.
- GitHub Pages visualization: `reports/index.html` (valid HTML); https://ai-frendly-datahub.github.io/PriceRadar/.
- Latest remote Pages check: HTTP 200, HTML.
- Local workspace audit: 70 Python files parsed, 0 syntax errors.
- Re-run audit from the workspace root: `python scripts/audit_ci_pages_readme.py --syntax-check --write`.
- Latest audit report: `_workspace/2026-04-14_github_ci_pages_readme_audit.md`.
- Latest Pages URL report: `_workspace/2026-04-14_github_pages_url_check.md`.
<!-- DATAHUB-OPS-AUDIT:END -->
