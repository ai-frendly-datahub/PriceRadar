# Data Quality Plan

- 생성 시각: `2026-04-23T14:45:24.863320+00:00`
- 우선순위: `P1`
- 데이터 품질 점수: `80`
- 가장 약한 축: `권위성`
- Governance: `medium`
- Primary Motion: `conversion`

## 현재 이슈

- 가장 약한 품질 축은 권위성(30)

## 필수 신호

- SKU 단위 가격 이력과 재고·품절 상태
- 쿠폰·카드혜택·배송비 같은 실제 구매가 구성요소
- 제조사·브랜드·공식 스토어 기준 가격 source

## 품질 게이트

- 상품명·옵션·용량을 canonical SKU key로 정규화
- 표시가·할인가·실구매가·배송비를 별도 필드로 유지
- 급격한 가격 변동은 outlier flag와 원문 URL을 함께 기록

## 다음 구현 순서

- 새 data_quality 계약을 기준으로 `reports/price_quality.json` 산출물을 매일 확인
- 공식 브랜드/스토어 후보를 ToS와 파싱 안정성 검증 후 단계적으로 활성화
- 가격 outlier와 품절 전환을 실제 collector 출력 필드에 연결

## 운영 규칙

- 원문 URL, 수집일, 이벤트 발생일은 별도 필드로 유지한다.
- 공식 source와 커뮤니티/시장 source를 같은 신뢰 등급으로 병합하지 않는다.
- collector가 인증키나 네트워크 제한으로 skip되면 실패를 숨기지 말고 skip 사유를 기록한다.
- 이 문서는 `scripts/build_data_quality_review.py --write-repo-plans`로 재생성한다.
