"""
가격 스코어러 - 상품의 구매 타이밍 점수 계산
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PriceScore:
    """가격 스코어링 결과"""

    product_id: str
    radar_score: float  # 최종 레이다 점수 (0.0 ~ 1.0)

    # 개별 점수
    discount_strength: float  # 할인 강도 (0.0 ~ 1.0)
    timing_rarity: float  # 타이밍 희소성 (0.0 ~ 1.0)
    popularity: float  # 인기도 (0.0 ~ 1.0)
    volatility: float  # 변동성 (0.0 ~ 1.0, 낮을수록 좋음)

    # 메타데이터
    current_price: int
    avg_price: Optional[int]
    saving_amount: Optional[int]  # 절약 금액
    explanation: str  # 사용자 설명


class PriceScorer:
    """가격 데이터를 분석하여 구매 타이밍 점수를 계산"""

    def __init__(self, config: dict) -> None:
        """
        Args:
            config: 스코어링 가중치 설정
                - discount_strength: 할인 강도 가중치 (기본 0.4)
                - timing_rarity: 타이밍 희소성 가중치 (기본 0.3)
                - popularity: 인기도 가중치 (기본 0.2)
                - volatility_penalty: 변동성 패널티 가중치 (기본 0.1)
        """
        self.weight_discount = config.get("discount_strength", 0.4)
        self.weight_timing = config.get("timing_rarity", 0.3)
        self.weight_popularity = config.get("popularity", 0.2)
        self.weight_volatility = config.get("volatility_penalty", 0.1)

    def calculate_score(
        self,
        product_id: str,
        current_price: int,
        avg_price: Optional[int] = None,
        list_price: Optional[int] = None,
        discount_rate: Optional[float] = None,
        is_lowest_now: bool = False,
        is_popular: bool = False,
        is_hotdeal: bool = False,
        price_history: Optional[list[int]] = None,
    ) -> PriceScore:
        """
        상품의 가격 정보를 기반으로 구매 타이밍 점수를 계산

        Args:
            product_id: 상품 ID
            current_price: 현재 가격
            avg_price: 평균 가격
            list_price: 정가
            discount_rate: 할인율 (0.0 ~ 1.0)
            is_lowest_now: 현재 최저가 여부
            is_popular: 인기 상품 여부
            is_hotdeal: 핫딜 여부
            price_history: 가격 히스토리 (최근 순)

        Returns:
            PriceScore 객체
        """
        # 1. 할인 강도 계산
        discount_strength = self._calculate_discount_strength(
            current_price, avg_price, list_price, discount_rate
        )

        # 2. 타이밍 희소성 계산
        timing_rarity = self._calculate_timing_rarity(
            current_price, price_history, is_lowest_now
        )

        # 3. 인기도 계산
        popularity = self._calculate_popularity(is_popular, is_hotdeal)

        # 4. 가격 변동성 계산
        volatility = self._calculate_volatility(price_history)

        # 5. 최종 레이다 점수 계산
        radar_score = (
            self.weight_discount * discount_strength
            + self.weight_timing * timing_rarity
            + self.weight_popularity * popularity
            + self.weight_volatility * (1.0 - volatility)  # 변동성이 낮을수록 좋음
        )

        # 6. 절약 금액 계산
        saving_amount = None
        if avg_price and avg_price > current_price:
            saving_amount = avg_price - current_price

        # 7. 사용자 설명 생성
        explanation = self._generate_explanation(
            current_price,
            avg_price,
            saving_amount,
            discount_rate,
            is_lowest_now,
            is_popular,
        )

        return PriceScore(
            product_id=product_id,
            radar_score=min(1.0, max(0.0, radar_score)),
            discount_strength=discount_strength,
            timing_rarity=timing_rarity,
            popularity=popularity,
            volatility=volatility,
            current_price=current_price,
            avg_price=avg_price,
            saving_amount=saving_amount,
            explanation=explanation,
        )

    def _calculate_discount_strength(
        self,
        current_price: int,
        avg_price: Optional[int],
        list_price: Optional[int],
        discount_rate: Optional[float],
    ) -> float:
        """할인 강도 계산 (0.0 ~ 1.0)"""
        scores = []

        # 평균가 대비 할인율
        if avg_price and avg_price > current_price:
            rate = (avg_price - current_price) / avg_price
            scores.append(min(1.0, rate * 2))  # 50% 할인 = 1.0

        # 정가 대비 할인율
        if list_price and list_price > current_price:
            rate = (list_price - current_price) / list_price
            scores.append(min(1.0, rate * 2))

        # 명시적 할인율
        if discount_rate is not None:
            scores.append(min(1.0, discount_rate * 2))

        return max(scores) if scores else 0.0

    def _calculate_timing_rarity(
        self,
        current_price: int,
        price_history: Optional[list[int]],
        is_lowest_now: bool,
    ) -> float:
        """타이밍 희소성 계산 (0.0 ~ 1.0)"""
        # 최저가 태그가 있으면 높은 점수
        if is_lowest_now:
            return 1.0

        # 가격 히스토리가 있으면 비교
        if price_history and len(price_history) > 0:
            min_price = min(price_history)
            max_price = max(price_history)

            if max_price == min_price:
                return 0.5  # 가격 변동 없음

            # 현재 가격이 히스토리 범위에서 어디에 위치하는지
            position = (max_price - current_price) / (max_price - min_price)
            return min(1.0, max(0.0, position))

        return 0.3  # 기본값

    def _calculate_popularity(self, is_popular: bool, is_hotdeal: bool) -> float:
        """인기도 계산 (0.0 ~ 1.0)"""
        score = 0.0

        if is_popular:
            score += 0.5
        if is_hotdeal:
            score += 0.5

        return min(1.0, score)

    def _calculate_volatility(self, price_history: Optional[list[int]]) -> float:
        """가격 변동성 계산 (0.0 ~ 1.0, 높을수록 변동이 심함)"""
        if not price_history or len(price_history) < 2:
            return 0.0

        # 표준편차 / 평균 (변동계수)
        avg = sum(price_history) / len(price_history)
        if avg == 0:
            return 0.0

        variance = sum((p - avg) ** 2 for p in price_history) / len(price_history)
        std_dev = variance**0.5
        cv = std_dev / avg

        # 변동계수를 0~1 범위로 정규화 (0.3 이상이면 1.0)
        return min(1.0, cv / 0.3)

    def _generate_explanation(
        self,
        current_price: int,
        avg_price: Optional[int],
        saving_amount: Optional[int],
        discount_rate: Optional[float],
        is_lowest_now: bool,
        is_popular: bool,
    ) -> str:
        """사용자를 위한 설명 생성"""
        parts = []

        if is_lowest_now:
            parts.append("현재 최저가입니다")

        if saving_amount and saving_amount > 0:
            parts.append(f"평균보다 {saving_amount:,}원 저렴합니다")

        if discount_rate and discount_rate > 0.2:
            parts.append(f"{int(discount_rate * 100)}% 할인 중입니다")

        if is_popular:
            parts.append("많은 사람들이 구매하고 있습니다")

        if not parts:
            parts.append("구매를 고려해볼 만한 상품입니다")

        return ". ".join(parts) + "."
