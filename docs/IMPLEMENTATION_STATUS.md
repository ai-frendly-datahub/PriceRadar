# PriceRadar 구현 상태

최종 업데이트: 2025-11-24

## 실행 결과 요약

### ✅ 성공적으로 구현된 기능

#### 1. 데이터 수집 (Collectors)

**폴센트 (Fallcent) Collector** ✓
- **상태**: 완전히 작동
- **수집 성과**:
  - fallcent_main: 105개 상품
  - fallcent_food: 105개 상품 (식품 급락)
  - fallcent_electronics: 105개 상품 (가전 급락)
- **총 수집**: 315개 아이템
- **구현 파일**: [priceradar/collectors/fallcent_collector.py](../priceradar/collectors/fallcent_collector.py)

**에누리 (Enuri) Collector** ⚠️
- **상태**: 구현 완료, 데이터 추출 이슈
- **수집 성과**: 0개 (JavaScript 구조 변경으로 추정)
- **원인**: jsonPopGoods 변수가 선언만 되고 값이 별도로 할당되는 구조
- **향후 계획**: 페이지 구조 재분석 필요
- **구현 파일**: [priceradar/collectors/enuri_collector.py](../priceradar/collectors/enuri_collector.py)

#### 2. 데이터 저장 (DuckDB)

**상품 데이터**:
- 총 92개 상품 저장
- 플랫폼: coupang (100%)
- 카테고리: electronics (91개), all (1개)

**가격 스냅샷**:
- 총 315개 스냅샷 저장
- 시계열 데이터 정상 수집

**가격 스코어**:
- 총 92개 상품 스코어링 완료
- 평균 실행 시간: 0.87초

#### 3. HTML 리포트 생성

**리포트 파일**: [docs/reports/2025-11-24/index.html](reports/2025-11-24/index.html)

**상위 5개 딜**:
1. **SD7 실리콘 수모** - 8,800원 (점수 0.87, 46% 할인)
2. **요즘 플레인 그릭요거트** - 7,700원 (점수 0.85, 44% 할인)
3. **YAPOGI 빈백 소파** - 22,600원 (점수 0.83, 41% 할인)
4. **브로드쇼핑 모자** - 14,200원 (점수 0.77, 34% 할인)
5. **파미레 실리콘 용기** - 26,190원 (점수 0.76, 32% 할인)

## 실행 통계

```bash
python main.py --mode once --report
```

**실행 결과** (2025-11-24 15:29:29):
- ✓ 데이터 수집: 315개 아이템 (14.67초)
- ✓ 가격 스코어링: 92개 상품 (0.87초)
- ✓ HTML 리포트 생성: 성공
- ✓ 총 실행 시간: ~16초

**데이터베이스 상태**:
```
총 상품 수: 92
총 스냅샷 수: 315
총 스코어 수: 92
카테고리별 상품 수:
  - electronics: 91개
  - all: 1개
```

## 활성 데이터 소스

| 소스 ID | 이름 | 타입 | 상태 | 수집 결과 |
|---------|------|------|------|-----------|
| fallcent_main | 폴센트 메인 | C3_fallcent | ✅ 작동 | 105개 |
| fallcent_food | 폴센트 식품 급락 | C3_fallcent_category | ✅ 작동 | 105개 |
| fallcent_electronics | 폴센트 가전 급락 | C3_fallcent_category | ✅ 작동 | 105개 |
| enuri_main | 에누리 메인 | C3_enuri | ⚠️ 이슈 | 0개 |
| enuri_electronics | 에누리 가전/TV | C3_enuri_category | ⚠️ 이슈 | 0개 |

## 스코어링 성능

**4축 가중치** (config/config.yaml):
```yaml
scoring:
  discount_strength: 0.4      # 할인 강도
  timing_rarity: 0.3          # 가격 타이밍 희소성
  popularity: 0.2             # 인기도/수요
  volatility_penalty: 0.1     # 가격 안정성
```

**스코어 분포**:
- 최고 점수: 0.87
- 평균 점수: ~0.70 (추정)
- 대부분 0.70~0.87 범위 (할인율 27~46%)

## 주요 발견 사항

### 성공 요인

1. **폴센트 데이터 품질**:
   - 쿠팡 전문 서비스로 데이터 일관성 높음
   - 할인율, 가격 정보 정확
   - 최저가 태그 신뢰도 높음

2. **HTML 구조 안정성**:
   - 폴센트 페이지 구조가 일관적
   - CSS 선택자 기반 파싱 안정적

3. **스코어링 정확도**:
   - 할인율 기반 스코어링 효과적
   - 상위 딜들이 실제로 좋은 가격대

### 개선 필요 사항

1. **에누리 Collector**:
   - JavaScript 구조 재분석 필요
   - 대안: API 엔드포인트 찾기 또는 다른 파싱 방법

2. **카테고리 정확도**:
   - 현재 대부분 'electronics'로 분류됨
   - 실제 상품은 다양한 카테고리 (식품, 생활, 패션 등)
   - 폴센트 URL 파라미터 분석 필요

3. **중복 제거**:
   - 같은 상품이 여러 소스에서 수집될 수 있음
   - 상품 ID 정규화 로직 필요

## 다음 단계

### Phase 2A: 즉시 개선 (P0)

- [ ] **폴센트 카테고리 정확도 개선**
  - URL 파라미터 분석
  - 실제 카테고리 매핑

- [ ] **에누리 Collector 수정**
  - 페이지 구조 재분석
  - JSON 데이터 추출 방법 개선

### Phase 2B: 데이터 품질 (P1)

- [ ] **중복 제거 로직**
  - 상품 URL 정규화
  - 동일 상품 감지

- [ ] **에러 핸들링 강화**
  - 네트워크 오류 재시도
  - 부분 실패 처리

### Phase 2C: 추가 소스 (P2)

- [ ] **다나와 Collector**
  - IT/가전 전문
  - 상세 스펙 정보

- [ ] **역대가 Collector**
  - 가격 히스토리 풍부
  - 쿠팡 전문

## 테스트 명령어

```bash
# 전체 파이프라인 실행
python main.py --mode once --report

# Collector만 테스트
python test_collectors.py

# 데이터베이스 확인
python check_db.py

# 에누리 디버그
python test_enuri_debug.py
```

## 리소스

- **데이터 소스 전략**: [DATA_SOURCES.md](DATA_SOURCES.md)
- **아키텍처**: [ARCHITECTURE.md](ARCHITECTURE.md)
- **개발 로드맵**: [ROADMAP.md](ROADMAP.md)
- **PRD**: [PRD.md](PRD.md)
