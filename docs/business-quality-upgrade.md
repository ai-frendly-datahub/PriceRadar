# Business Quality Upgrade

- Generated: `2026-04-14T04:48:11.525239+00:00`
- Portfolio verdict: `충분`
- Business value score: `76.4`
- Upgrade phase: P1 가격 계약 필드 감시
- Primary motion: `conversion`
- Weakest dimension: `authority`

## Current Evidence

- Primary rows: `118559`
- Today raw rows: `298`
- Latest report items: `100`
- Match rate: `100.0%`
- Collection errors: `0`
- Freshness gap: `0`

## Upgrade Actions

- quality_outputs.tracked_event_models로 가격/혜택/재고 이벤트 모델을 명시해 공통 감사에서 누락되지 않게 한다.
- 공식 브랜드/스토어 source 후보는 ToS, selector stability, stock fidelity 검증 후 authority 공백을 보완한다.
- 가격 outlier와 품절 전환을 reports/price_quality.json의 핵심 일일 점검 항목으로 유지한다.

## Quality Contracts

- `config/sources.yaml`: output `reports/price_quality.json`, tracked `sku_price_snapshot, purchase_benefit_snapshot, stock_status_transition`, backlog items `3`

## Contract Gaps

- None.
