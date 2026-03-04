# PriceRadar 로드맵

## Phase 1: MVP 구축 (완료)

### ✅ 완료된 작업

1. **프로젝트 구조 설정**
   - [x] WineRadar 기반 디렉터리 구조
   - [x] pyproject.toml, pytest.ini, .editorconfig
   - [x] 개발 환경 설정 (black, ruff, mypy)

2. **핵심 모듈 구현**
   - [x] Collectors: HTML 기반 데이터 수집
   - [x] Analyzers: 4축 가격 스코어링
   - [x] Graph Store: DuckDB 저장소
   - [x] Reporters: HTML 리포트 생성

3. **데모 및 문서**
   - [x] demo_pipeline.py 구현
   - [x] main.py 구현 (once/scheduler 모드)
   - [x] ARCHITECTURE.md, PRD.md 작성
   - [x] README.md 업데이트

## Phase 2: 실제 데이터 연동 (현재)

### 🚧 진행 중

1. **폴센트 크롤러 구현**
   - [ ] 폴센트 메인 페이지 파싱
   - [ ] 카테고리별 급락 페이지 파싱
   - [ ] 지금 최저가/인기 상품 페이지 파싱
   - [ ] robots.txt 확인 및 준수
   - [ ] 요청 간격 조절 (rate limiting)

2. **데이터 품질 개선**
   - [ ] 가격 히스토리 누적
   - [ ] 중복 제거 로직
   - [ ] 에러 핸들링 강화

3. **테스트 작성**
   - [ ] Unit 테스트 (collectors, analyzers, graph)
   - [ ] Integration 테스트 (전체 파이프라인)
   - [ ] E2E 테스트 (main.py 실행)

### 우선순위

**P0 (필수)**
- [ ] 폴센트 크롤러 구현
- [ ] 테스트 작성

**P1 (중요)**
- [ ] GitHub Actions CI/CD
- [ ] HTML 리포트 고도화

## Phase 3: 자동화 및 배포

### 📅 계획

1. **GitHub Actions**
   - [ ] 일일 자동 수집 워크플로
   - [ ] GitHub Pages 배포
   - [ ] Artifact 백업 (DuckDB)

2. **리포트 고도화**
   - [ ] Chart.js 기반 시각화
   - [ ] 카테고리별 필터링
   - [ ] 가격 히스토리 그래프

3. **알림 채널**
   - [ ] 텔레그램 봇
   - [ ] 이메일 알림
   - [ ] Webhook 지원

## Phase 4: 고급 기능

### 📅 향후 계획

1. **개인화**
   - [ ] 사용자별 관심 카테고리
   - [ ] 가격대 필터링
   - [ ] 워치리스트

2. **예측 기능**
   - [ ] 가격 예측 (ML 기반)
   - [ ] 최적 구매 타이밍 추천
   - [ ] 가격 하락 예측

3. **다른 라이더 통합**
   - [ ] TrendRadar 연동
   - [ ] WineRadar 연동
   - [ ] 공통 RadarItem 인터페이스

## Phase 5: 플랫폼 확장

### 📅 장기 계획

1. **MCP 서버**
   - [ ] Claude Desktop 연동
   - [ ] Tools 구현 (get_deals, search_product 등)

2. **API 서버**
   - [ ] REST API
   - [ ] WebSocket (실시간 알림)
   - [ ] 인증/권한

3. **모바일 앱**
   - [ ] React Native 앱
   - [ ] 푸시 알림
   - [ ] 오프라인 모드

## 마일스톤

| Phase | 목표 | 예상 기간 | 상태 |
|-------|------|-----------|------|
| Phase 1 | MVP 구축 | 1주 | ✅ 완료 |
| Phase 2 | 실제 데이터 연동 | 2주 | 🚧 진행 중 |
| Phase 3 | 자동화 및 배포 | 2주 | 📅 계획 |
| Phase 4 | 고급 기능 | 4주 | 📅 향후 |
| Phase 5 | 플랫폼 확장 | 8주 | 📅 장기 |

## KPI 목표

### Phase 2
- [ ] 일일 수집 성공률 ≥ 95%
- [ ] 상품 수 ≥ 100개/일
- [ ] 테스트 커버리지 ≥ 80%

### Phase 3
- [ ] GitHub Actions 안정성 ≥ 95%
- [ ] 리포트 생성 성공률 ≥ 95%
- [ ] 상위 딜 평균 점수 ≥ 0.7

### Phase 4
- [ ] 사용자 수 ≥ 100명
- [ ] 알림 발송 성공률 ≥ 90%
- [ ] 가격 예측 정확도 ≥ 70%
