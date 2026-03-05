# PRICERADAR

가격 비교·추적 레이더. Enuri, Fallcent 등 가격비교 사이트 스크래핑 → 가격 스코어링 → DuckDB 그래프 저장. Pydantic 모델 사용 (유일).

## STRUCTURE

```
PriceRadar/
├── priceradar/                     # 단일 패키지 + sub-packages (하이브리드)
│   ├── collectors/
│   │   ├── base.py                 # BaseCollector ABC
│   │   ├── enuri_collector.py      # 에누리 가격비교
│   │   ├── fallcent_collector.py   # 폴센트 가격비교
│   │   ├── html_collector.py      # 범용 HTML 스크래핑
│   │   └── registry.py            # CollectorRegistry 팩토리
│   ├── analyzers/                  # 가격 분석
│   ├── reporters/                  # HTML 리포트
│   ├── sources/                    # 소스 정의
│   ├── graph/
│   │   └── graph_store.py         # DuckDB 그래프 (가격 추이)
│   ├── pipeline.py                # 파이프라인 오케스트레이션 (UNIQUE)
│   ├── scoring.py                 # 가격 스코어링 로직 (UNIQUE)
│   ├── models.py                  # Pydantic 모델 (dataclass 아님!)
│   ├── config.py                  # YAML 대신 Python config
│   ├── storage.py                 # DuckDB 저장
│   ├── search_index.py            # FTS5 검색
│   ├── raw_logger.py              # JSONL 로깅
│   ├── nl_query.py                # 자연어 쿼리
│   └── mcp_server/                # MCP 서버
├── config/
│   ├── config.yaml                # 확장된 설정 (scoring weights, thresholds, retry)
│   └── sources.yaml               # 가격 소스 정의
└── main.py                        # --mode once --report
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| 새 가격 소스 | `priceradar/collectors/` | BaseCollector 상속 + registry 등록 |
| 스코어링 로직 | `priceradar/scoring.py` | discount_strength, timing, volatility |
| 파이프라인 흐름 | `priceradar/pipeline.py` | collect → score → store → report |
| 설정 임계값 | `config/config.yaml` | min_discount_rate, price_ranges 등 |

## DEVIATIONS FROM TEMPLATE

- **Pydantic 모델**: `models.py`가 dataclass 대신 Pydantic BaseModel 사용 (워크스페이스 유일)
- **Pipeline 모듈**: `pipeline.py`로 파이프라인 로직 분리 (main.py에 인라인 아님)
- **Scoring**: `scoring.py` — 할인율/타이밍/변동성 기반 가격 점수 산출
- **Config**: `config.py` Python 모듈 + `config.yaml` 확장 설정 병용
- **BeautifulSoup**: RSS 대신 HTML 스크래핑 위주 (`beautifulsoup4` 의존성)
- **하이브리드 구조**: 단일 `priceradar/` 패키지 안에 sub-packages (Advanced 중 유일)

## COMMANDS

```bash
python main.py --mode once --report
pytest tests/unit -m unit
pytest tests/ -m "not network"
```
