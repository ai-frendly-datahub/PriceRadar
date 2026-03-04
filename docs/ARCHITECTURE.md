# PriceRadar 아키텍처

## 개요

PriceRadar는 여러 쇼핑몰의 가격 변동과 딜 정보를 수집하고 분석하여, 사용자에게 최적의 구매 타이밍을 제공하는 시스템입니다.

## 시스템 구조

```
┌─────────────┐
│  Data       │
│  Sources    │
│ (Fallcent)  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Collectors  │  RawItem 수집
│             │  - HtmlCollector
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Analyzers   │  가격 분석 및 스코어링
│             │  - PriceScorer
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Graph Store │  DuckDB 기반 저장
│             │  - Products
│             │  - PriceSnapshots
│             │  - PriceScores
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Reporters   │  HTML 리포트 생성
│             │  - HtmlReporter
└─────────────┘
```

## 핵심 모듈

### 1. Collectors (수집기)

**책임**: 외부 소스에서 가격 데이터 수집

- `BaseCollector`: 모든 수집기의 기본 인터페이스
- `HtmlCollector`: BeautifulSoup 기반 HTML 파싱
- `RawItem`: 수집한 원시 데이터 표현

**주요 기능**:
- URL에서 HTML 가져오기
- CSS 선택자로 상품 정보 추출
- 가격, 할인율, 평균가 파싱

### 2. Analyzers (분석기)

**책임**: 가격 데이터 분석 및 구매 타이밍 점수 계산

- `PriceScorer`: 4가지 축으로 상품 스코어링
  - 할인 강도 (Discount Strength)
  - 타이밍 희소성 (Timing Rarity)
  - 인기도 (Popularity)
  - 가격 변동성 (Volatility)

**점수 계산 공식**:
```
radar_score =
  0.4 * discount_strength +
  0.3 * timing_rarity +
  0.2 * popularity +
  0.1 * (1 - volatility)
```

### 3. Graph Store (저장소)

**책임**: DuckDB 기반 데이터 영속화 및 조회

**테이블 구조**:
- `products`: 상품 마스터 정보
- `price_snapshots`: 가격 스냅샷 (시계열)
- `price_scores`: 레이다 점수 (시계열)

**주요 API**:
- `save_raw_item()`: RawItem 저장
- `save_price_score()`: PriceScore 저장
- `get_top_deals()`: 상위 딜 조회
- `get_product_history()`: 가격 히스토리 조회

### 4. Reporters (리포터)

**책임**: HTML 리포트 생성

- `HtmlReporter`: Jinja2 기반 리포트 생성
- 카드 형식으로 상위 딜 표시
- 레이다 점수 시각화

## 데이터 흐름

1. **수집 (Collection)**
   ```
   Fallcent 웹페이지 → HtmlCollector → RawItem[]
   ```

2. **분석 (Analysis)**
   ```
   RawItem → PriceScorer.calculate_score() → PriceScore
   ```

3. **저장 (Storage)**
   ```
   RawItem → GraphStore.save_raw_item()
   PriceScore → GraphStore.save_price_score()
   ```

4. **조회 (Query)**
   ```
   GraphStore.get_top_deals() → Deal[]
   ```

5. **리포팅 (Reporting)**
   ```
   Deal[] → HtmlReporter.generate_report() → HTML 파일
   ```

## 확장 포인트

### 새로운 수집기 추가

1. `BaseCollector`를 상속한 클래스 생성
2. `collect()` 메서드 구현
3. `CollectorRegistry`에 등록

### 새로운 분석 지표 추가

1. `PriceScorer`에 새로운 계산 메서드 추가
2. `PriceScore` 데이터 클래스에 필드 추가
3. 가중치 설정 업데이트

### 새로운 리포트 형식 추가

1. `BaseReporter`를 상속한 클래스 생성
2. Jinja2 템플릿 작성
3. `generate_report()` 메서드 구현

## 설정 관리

- `config/config.yaml`: 핵심 설정 (가중치, 임계값 등)
- `config/sources.yaml`: 데이터 소스 정의

## 의존성

- **requests**: HTTP 클라이언트
- **beautifulsoup4**: HTML 파싱
- **duckdb**: 임베디드 데이터베이스
- **jinja2**: 템플릿 엔진
- **pydantic**: 데이터 검증
- **pyyaml**: 설정 파일 파싱
