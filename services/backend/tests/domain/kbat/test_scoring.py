from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.kbat import (
    KBatDomainScores,
    KBatRiskLevel,
    calculate_burnout_result,
    calculate_domain_average,
    classify_risk_level,
)


def scores(value: float) -> KBatDomainScores:
    """4개 영역이 모두 같은 평균일 때의 점수 -- 전체 평균도 그 값과 같아진다."""
    return KBatDomainScores(
        exhaustion=value,
        mental_distance=value,
        cognitive_control=value,
        emotional_control=value,
    )


class TestClassifyRiskLevelBoundaries:
    """요구사항 표의 여섯 경계값을 그대로 검증한다."""

    @pytest.mark.parametrize(
        ("total_average", "expected"),
        [
            (1.00, KBatRiskLevel.GOOD),
            (2.53, KBatRiskLevel.GOOD),
            (2.54, KBatRiskLevel.CAUTION),
            (2.95, KBatRiskLevel.CAUTION),
            (2.96, KBatRiskLevel.WARNING),
            (5.00, KBatRiskLevel.WARNING),
        ],
    )
    def test_boundary_values(
        self, total_average: float, expected: KBatRiskLevel
    ) -> None:
        assert classify_risk_level(total_average) is expected

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            classify_risk_level(0.99)
        with pytest.raises(ValueError):
            classify_risk_level(5.01)


class TestCalculateDomainAverage:
    def test_averages_answers(self) -> None:
        assert calculate_domain_average([1, 2, 3, 4, 5]) == 3.0

    def test_empty_answers_returns_none_not_zero(self) -> None:
        # 응답이 없다고 0점(가장 낮은 위험)으로 잘못 채워 넣지 않는다.
        assert calculate_domain_average([]) is None

    def test_out_of_range_answer_raises(self) -> None:
        with pytest.raises(ValueError):
            calculate_domain_average([0, 3])
        with pytest.raises(ValueError):
            calculate_domain_average([3, 6])


class TestCalculateBurnoutResult:
    def test_total_average_is_mean_of_domain_averages_not_all_questions(self) -> None:
        # 탈진 8문항 vs 심적거리 4문항처럼 문항 수가 달라도, 전체 평균은
        # "4개 영역 평균의 평균"이라 문항 수가 많은 영역에 쏠리지 않는다.
        result = calculate_burnout_result(
            KBatDomainScores(
                exhaustion=5.0,
                mental_distance=1.0,
                cognitive_control=1.0,
                emotional_control=1.0,
            )
        )
        assert result.total_average == pytest.approx(2.0)
        assert result.risk_level is KBatRiskLevel.GOOD

    def test_domain_averages_pass_through_unchanged(self) -> None:
        result = calculate_burnout_result(
            KBatDomainScores(
                exhaustion=4.1,
                mental_distance=3.2,
                cognitive_control=2.3,
                emotional_control=1.4,
            )
        )
        assert result.exhaustion_average == pytest.approx(4.1)
        assert result.mental_distance_average == pytest.approx(3.2)
        assert result.cognitive_control_average == pytest.approx(2.3)
        assert result.emotional_control_average == pytest.approx(1.4)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1.00, KBatRiskLevel.GOOD),
            (2.53, KBatRiskLevel.GOOD),
            (2.54, KBatRiskLevel.CAUTION),
            (2.95, KBatRiskLevel.CAUTION),
            (2.96, KBatRiskLevel.WARNING),
            (5.00, KBatRiskLevel.WARNING),
        ],
    )
    def test_uniform_domain_scores_match_boundary_table(
        self, value: float, expected: KBatRiskLevel
    ) -> None:
        result = calculate_burnout_result(scores(value))
        assert result.total_average == pytest.approx(value)
        assert result.risk_level is expected

    def test_domain_score_out_of_range_rejected_by_model(self) -> None:
        with pytest.raises(ValidationError):
            KBatDomainScores(
                exhaustion=0.5,
                mental_distance=3.0,
                cognitive_control=3.0,
                emotional_control=3.0,
            )
        with pytest.raises(ValidationError):
            KBatDomainScores(
                exhaustion=3.0,
                mental_distance=3.0,
                cognitive_control=3.0,
                emotional_control=5.5,
            )
