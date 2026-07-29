from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.domain.risk import (
    DEFAULT_CONFIG,
    BaselineStatus,
    BurnoutRiskEngine,
    BurnoutRiskEvaluationRequest,
    BurnoutRiskEvaluationResponse,
    CurrentRiskSignals,
    DataQuality,
    EmotionProbabilities,
    FactorCode,
    FactorKind,
    PersonalBaseline,
    RiskCategory,
    RiskLevel,
    risk_level_for_score,
)


def probabilities(joy: float = 0.5) -> EmotionProbabilities:
    remaining = (1.0 - joy) / 5
    return EmotionProbabilities(
        **{
            "기쁨": joy,
            "불안": remaining,
            "당황": remaining,
            "분노": remaining,
            "슬픔": remaining,
            "무기력": remaining,
        }
    )


def full_current(**overrides: object) -> CurrentRiskSignals:
    values: dict[str, object] = {
        "sleep_minutes": 420,
        "work_or_study_minutes": 300,
        "rest_minutes": 90,
        "exercise_minutes": 25,
        "schedule_count": 3,
        "subjective_stress": 4,
        "subjective_fatigue": 3,
        "emotion_probabilities": probabilities(0.62),
        "emotion_confidence": 1,
        "emotion_uncertain": False,
    }
    values.update(overrides)
    return CurrentRiskSignals.model_validate(values)


def full_baseline(**overrides: object) -> PersonalBaseline:
    values: dict[str, object] = {
        "sleep_minutes": 420,
        "work_or_study_minutes": 300,
        "rest_minutes": 90,
        "exercise_minutes": 25,
        "schedule_count": 3,
        "subjective_stress": 4,
        "subjective_fatigue": 3,
        "negative_emotion_probability": 0.38,
        "sample_days": 18,
    }
    values.update(overrides)
    return PersonalBaseline.model_validate(values)


def factor_codes(result: BurnoutRiskEvaluationResponse) -> list[FactorCode]:
    return [item.code for item in result.factors]


def evaluate(
    current: CurrentRiskSignals,
    baseline: PersonalBaseline | None = None,
) -> BurnoutRiskEvaluationResponse:
    return BurnoutRiskEngine().evaluate(current=current, baseline=baseline)


def test_equal_current_and_baseline_is_low() -> None:
    result = evaluate(full_current(), full_baseline())

    assert result.score == 0
    assert result.level is RiskLevel.LOW
    assert result.is_provisional is False
    assert result.baseline_status is BaselineStatus.READY
    assert result.data_quality is DataQuality.SUFFICIENT
    assert result.factors == []
    assert set(result.category_scores) == {
        "sleep",
        "workload",
        "recovery",
        "emotion",
        "subjective",
    }


@pytest.mark.parametrize(
    ("current", "baseline", "expected"),
    [
        (
            CurrentRiskSignals(sleep_minutes=300),
            PersonalBaseline(sleep_minutes=420, sample_days=14),
            FactorCode.SLEEP_DECREASE,
        ),
        (
            CurrentRiskSignals(work_or_study_minutes=600),
            PersonalBaseline(work_or_study_minutes=300, sample_days=14),
            FactorCode.WORKLOAD_INCREASE,
        ),
        (
            CurrentRiskSignals(schedule_count=8),
            PersonalBaseline(schedule_count=3, sample_days=14),
            FactorCode.SCHEDULE_OVERLOAD,
        ),
        (
            CurrentRiskSignals(rest_minutes=20),
            PersonalBaseline(rest_minutes=90, sample_days=14),
            FactorCode.REST_DECREASE,
        ),
        (
            CurrentRiskSignals(exercise_minutes=0),
            PersonalBaseline(exercise_minutes=25, sample_days=14),
            FactorCode.EXERCISE_DECREASE,
        ),
        (
            CurrentRiskSignals(
                emotion_probabilities=probabilities(0.1),
                emotion_confidence=1,
                emotion_uncertain=False,
            ),
            PersonalBaseline(
                negative_emotion_probability=0.3,
                sample_days=14,
            ),
            FactorCode.NEGATIVE_EMOTION_INCREASE,
        ),
        (
            CurrentRiskSignals(subjective_stress=9),
            PersonalBaseline(subjective_stress=3, sample_days=14),
            FactorCode.SUBJECTIVE_STRESS,
        ),
    ],
)
def test_each_signal_can_contribute_in_isolation(
    current: CurrentRiskSignals,
    baseline: PersonalBaseline,
    expected: FactorCode,
) -> None:
    result = evaluate(current, baseline)

    assert expected in factor_codes(result)
    assert result.score > 0
    assert result.is_provisional is True
    assert result.data_quality is DataQuality.INSUFFICIENT


def test_multiple_risk_signals_combine() -> None:
    result = evaluate(
        full_current(
            sleep_minutes=250,
            work_or_study_minutes=700,
            rest_minutes=10,
            schedule_count=8,
            subjective_stress=10,
        ),
        full_baseline(),
    )

    assert result.score >= 50
    assert result.level in {RiskLevel.HIGH, RiskLevel.VERY_HIGH}
    assert len([f for f in result.factors if f.kind is FactorKind.RISK]) >= 5
    assert result.score == round(
        sum(
            factor.contribution
            for factor in result.factors
            if factor.kind is FactorKind.RISK
        ),
        2,
    )


def test_high_joy_and_no_negative_increase_adds_no_emotion_risk() -> None:
    result = evaluate(
        CurrentRiskSignals(
            emotion_probabilities=probabilities(0.9),
            emotion_confidence=1,
            emotion_uncertain=False,
        ),
        PersonalBaseline(
            negative_emotion_probability=0.2,
            sample_days=14,
        ),
    )

    assert FactorCode.NEGATIVE_EMOTION_INCREASE not in factor_codes(result)
    assert result.category_scores[RiskCategory.EMOTION] == 0


def test_lower_emotion_confidence_reduces_contribution() -> None:
    baseline = PersonalBaseline(
        negative_emotion_probability=0.2,
        sample_days=14,
    )
    high = evaluate(
        CurrentRiskSignals(
            emotion_probabilities=probabilities(0.2),
            emotion_confidence=1,
            emotion_uncertain=False,
        ),
        baseline,
    )
    low = evaluate(
        CurrentRiskSignals(
            emotion_probabilities=probabilities(0.2),
            emotion_confidence=0,
            emotion_uncertain=False,
        ),
        baseline,
    )

    assert (
        low.category_scores[RiskCategory.EMOTION]
        < high.category_scores[RiskCategory.EMOTION]
    )
    assert low.category_scores[RiskCategory.EMOTION] > 0


def test_emotion_uncertainty_reduces_contribution() -> None:
    baseline = PersonalBaseline(
        negative_emotion_probability=0.2,
        sample_days=14,
    )
    certain = evaluate(
        CurrentRiskSignals(
            emotion_probabilities=probabilities(0.2),
            emotion_confidence=1,
            emotion_uncertain=False,
        ),
        baseline,
    )
    uncertain = evaluate(
        CurrentRiskSignals(
            emotion_probabilities=probabilities(0.2),
            emotion_confidence=1,
            emotion_uncertain=True,
        ),
        baseline,
    )

    assert (
        uncertain.category_scores[RiskCategory.EMOTION]
        < certain.category_scores[RiskCategory.EMOTION]
    )


def test_missing_emotion_confidence_uses_nonzero_floor() -> None:
    result = evaluate(
        CurrentRiskSignals(emotion_probabilities=probabilities(0.1)),
        PersonalBaseline(
            negative_emotion_probability=0.2,
            sample_days=14,
        ),
    )

    assert result.category_scores[RiskCategory.EMOTION] > 0


@pytest.mark.parametrize(
    ("baseline", "status"),
    [
        (None, BaselineStatus.MISSING),
        (PersonalBaseline(sample_days=6), BaselineStatus.INSUFFICIENT),
    ],
)
def test_baseline_limitations_are_provisional_and_informational(
    baseline: PersonalBaseline | None,
    status: BaselineStatus,
) -> None:
    result = evaluate(full_current(sleep_minutes=240), baseline)
    info = next(
        item
        for item in result.factors
        if item.code is FactorCode.INSUFFICIENT_BASELINE
    )

    assert result.baseline_status is status
    assert result.is_provisional is True
    assert result.score <= DEFAULT_CONFIG.provisional_score_cap
    assert info.kind is FactorKind.INFORMATIONAL
    assert info.contribution == 0


def test_ready_but_partial_baseline_uses_provisional_fallback() -> None:
    result = evaluate(
        full_current(sleep_minutes=240),
        PersonalBaseline(sample_days=14),
    )

    assert result.baseline_status is BaselineStatus.READY
    assert result.is_provisional is True
    assert result.score <= DEFAULT_CONFIG.provisional_score_cap


def test_seven_baseline_days_is_ready_boundary() -> None:
    result = evaluate(
        CurrentRiskSignals(sleep_minutes=420),
        PersonalBaseline(sleep_minutes=420, sample_days=7),
    )

    assert result.baseline_status is BaselineStatus.READY


def test_mostly_missing_current_has_insufficient_data() -> None:
    result = evaluate(
        CurrentRiskSignals(sleep_minutes=300),
        PersonalBaseline(sleep_minutes=420, sample_days=14),
    )

    assert result.data_quality is DataQuality.INSUFFICIENT
    assert FactorCode.INSUFFICIENT_DATA in factor_codes(result)
    assert result.summary.available_signal_count == 1
    assert result.summary.missing_signal_count == 6
    assert result.summary.available_category_count == 1
    assert result.summary.missing_category_count == 4


def test_missing_categories_are_omitted_and_weights_are_renormalized() -> None:
    isolated = evaluate(
        CurrentRiskSignals(sleep_minutes=300),
        PersonalBaseline(sleep_minutes=420, sample_days=14),
    )
    complete = evaluate(
        full_current(sleep_minutes=300),
        full_baseline(),
    )

    assert set(isolated.category_scores) == {"sleep"}
    assert isolated.score > complete.score
    sleep_factor = next(
        item for item in isolated.factors if item.code is FactorCode.SLEEP_DECREASE
    )
    assert sleep_factor.weight > 0.99


@pytest.mark.parametrize(
    "invalid",
    [
        {
            "기쁨": 0.5,
            "불안": 0.1,
            "당황": 0.1,
            "분노": 0.1,
            "슬픔": 0.1,
            "무기력": 0.2,
        },
        {
            "기쁨": 0.5,
            "불안": 0.1,
            "당황": 0.1,
            "분노": 0.1,
            "슬픔": 0.1,
        },
        {
            "기쁨": 0.5,
            "불안": 0.1,
            "당황": 0.1,
            "분노": 0.1,
            "슬픔": 0.1,
            "공포": 0.1,
        },
        {
            "기쁨": -0.1,
            "불안": 0.3,
            "당황": 0.2,
            "분노": 0.2,
            "슬픔": 0.2,
            "무기력": 0.2,
        },
        {
            "기쁨": float("nan"),
            "불안": 0.2,
            "당황": 0.2,
            "분노": 0.2,
            "슬픔": 0.2,
            "무기력": 0.2,
        },
        {
            "기쁨": float("inf"),
            "불안": 0,
            "당황": 0,
            "분노": 0,
            "슬픔": 0,
            "무기력": 0,
        },
    ],
)
def test_invalid_emotion_probabilities_are_rejected(
    invalid: dict[str, float],
) -> None:
    with pytest.raises(ValidationError):
        EmotionProbabilities(**invalid)


@pytest.mark.parametrize(
    "values",
    [
        {"sleep_minutes": -1},
        {"sleep_minutes": float("nan")},
        {"rest_minutes": float("inf")},
        {"schedule_count": -1},
        {"subjective_stress": 11},
        {"emotion_confidence": 0.5},
    ],
)
def test_invalid_current_values_are_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CurrentRiskSignals.model_validate(values)


def test_zero_baseline_never_divides_by_zero() -> None:
    result = evaluate(
        CurrentRiskSignals(
            sleep_minutes=0,
            work_or_study_minutes=600,
            schedule_count=8,
        ),
        PersonalBaseline(
            sleep_minutes=0,
            work_or_study_minutes=0,
            schedule_count=0,
            sample_days=14,
        ),
    )

    assert 0 <= result.score <= 100
    assert result.is_provisional is True
    assert all(
        item.change_percent is None or abs(item.change_percent) < float("inf")
        for item in result.factors
    )


def test_extreme_values_are_clamped_to_contract_ranges() -> None:
    result = evaluate(
        full_current(
            sleep_minutes=0,
            work_or_study_minutes=1440,
            rest_minutes=0,
            exercise_minutes=0,
            schedule_count=1000,
            subjective_stress=10,
            subjective_fatigue=10,
            emotion_probabilities=probabilities(0),
        ),
        full_baseline(),
    )

    assert 0 <= result.score <= 100
    assert all(0 <= value <= 100 for value in result.category_scores.values())
    assert all(0 <= item.severity <= 1 for item in result.factors)
    assert all(0 <= item.contribution <= 100 for item in result.factors)


def test_fatigue_above_ten_uses_existing_deterministic_severity_cap() -> None:
    current = CurrentRiskSignals(subjective_fatigue=25)
    baseline = PersonalBaseline(subjective_fatigue=12, sample_days=14)

    first = evaluate(current, baseline)
    second = evaluate(current, baseline)
    fatigue_factor = next(
        item
        for item in first.factors
        if item.code is FactorCode.SUBJECTIVE_FATIGUE
    )

    assert first == second
    assert fatigue_factor.observed_value == 25
    assert fatigue_factor.baseline_value == 12
    assert fatigue_factor.severity == DEFAULT_CONFIG.subjective_severity_cap
    assert first.category_scores[RiskCategory.SUBJECTIVE] == 45


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (24.99, RiskLevel.LOW),
        (25.00, RiskLevel.MODERATE),
        (49.99, RiskLevel.MODERATE),
        (50.00, RiskLevel.HIGH),
        (74.99, RiskLevel.HIGH),
        (75.00, RiskLevel.VERY_HIGH),
        (100.00, RiskLevel.VERY_HIGH),
    ],
)
def test_level_threshold_boundaries(score: float, level: RiskLevel) -> None:
    assert risk_level_for_score(score) is level


@pytest.mark.parametrize(
    ("current_minutes", "category_score"),
    [
        (100, 0),
        (90, 20),
        (75, 60),
        (60, 100),
        (110, 0),
    ],
)
def test_sleep_piecewise_policy(
    current_minutes: float,
    category_score: float,
) -> None:
    result = evaluate(
        CurrentRiskSignals(sleep_minutes=current_minutes),
        PersonalBaseline(sleep_minutes=100, sample_days=14),
    )

    assert result.category_scores[RiskCategory.SLEEP] == category_score


def test_exercise_signal_is_capped_even_with_ready_baseline() -> None:
    result = evaluate(
        CurrentRiskSignals(exercise_minutes=0),
        PersonalBaseline(exercise_minutes=30, sample_days=14),
    )

    assert result.category_scores[RiskCategory.RECOVERY] == 30
    assert result.level is RiskLevel.MODERATE


def test_subjective_signal_cannot_produce_high_result_by_itself() -> None:
    result = evaluate(
        CurrentRiskSignals(subjective_stress=10),
        PersonalBaseline(subjective_stress=3, sample_days=14),
    )

    assert result.category_scores[RiskCategory.SUBJECTIVE] == 45
    assert result.score == 45
    assert result.level is RiskLevel.MODERATE


def test_provisional_results_never_reach_very_high() -> None:
    result = evaluate(
        CurrentRiskSignals(sleep_minutes=0),
        PersonalBaseline(sleep_minutes=420, sample_days=14),
    )

    assert result.score == DEFAULT_CONFIG.provisional_score_cap
    assert result.level is RiskLevel.HIGH
    assert result.is_provisional is True


def test_factors_are_sorted_by_contribution_descending() -> None:
    result = evaluate(
        full_current(
            sleep_minutes=260,
            work_or_study_minutes=600,
            rest_minutes=20,
            subjective_stress=8,
        ),
        full_baseline(),
    )
    ordering = [(item.contribution, item.code.value) for item in result.factors]

    assert ordering == sorted(ordering, key=lambda item: (-item[0], item[1]))
    assert result.summary.top_factor_codes == [
        item.code
        for item in result.factors
        if item.kind is FactorKind.RISK
    ][:3]


def test_engine_is_deterministic_and_field_order_independent() -> None:
    first_payload = {
        "sleep_minutes": 300,
        "rest_minutes": 30,
        "schedule_count": 6,
    }
    second_payload = dict(reversed(list(first_payload.items())))
    baseline = PersonalBaseline(
        sleep_minutes=420,
        rest_minutes=90,
        schedule_count=3,
        sample_days=14,
    )

    first = evaluate(CurrentRiskSignals.model_validate(first_payload), baseline)
    second = evaluate(CurrentRiskSignals.model_validate(second_payload), baseline)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_request_and_keyword_interfaces_match() -> None:
    current = full_current(sleep_minutes=300)
    baseline = full_baseline()
    request = BurnoutRiskEvaluationRequest(current=current, baseline=baseline)
    engine = BurnoutRiskEngine()

    assert engine.evaluate(request) == engine.evaluate(
        current=current,
        baseline=baseline,
    )
    with pytest.raises(ValueError):
        engine.evaluate(request, current=current)


def test_engine_version_and_json_serialization_are_stable() -> None:
    result = evaluate(full_current(sleep_minutes=300), full_baseline())
    serialized = result.model_dump(mode="json")

    assert result.engine_version == "burnout-risk-rules-v1"
    assert json.loads(json.dumps(serialized, allow_nan=False)) == serialized
    assert result.score == round(
        sum(
            item.contribution
            for item in result.factors
            if item.kind is FactorKind.RISK
        ),
        2,
    )


def test_config_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        cast(Any, DEFAULT_CONFIG).minimum_baseline_days = 1


def test_invalid_config_weight_sum_is_rejected() -> None:
    category = next(iter(dict(DEFAULT_CONFIG.category_weights)))
    with pytest.raises(ValueError, match="sum to 1.0"):
        replace(
            DEFAULT_CONFIG,
            category_weights=((category, 0.5),),
        )


def test_empty_current_is_explicitly_insufficient_not_normal_data() -> None:
    result = evaluate(CurrentRiskSignals(), None)

    assert result.score == 0
    assert result.is_provisional is True
    assert result.data_quality is DataQuality.INSUFFICIENT
    assert result.category_scores == {}
    assert factor_codes(result) == [
        FactorCode.INSUFFICIENT_BASELINE,
        FactorCode.INSUFFICIENT_DATA,
    ]
