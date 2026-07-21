from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai.src import signal as signal_package
from ai.src.schemas import (
    CombinedLevel,
    CombinedResultType,
    ReasonCode,
    SignalType,
)
from ai.src.signal import (
    AssessmentSignal,
    AssessmentSignalState,
    BehaviorSignal,
    BehaviorSignalState,
    EmotionSignal,
    EmotionSignalState,
    SignalAlignmentDirection,
    combine_signals,
)


def _assessment(
    state: AssessmentSignalState = AssessmentSignalState.NOT_ELEVATED,
    *,
    is_change_from_prior_anchor: bool = False,
    alignment_direction: SignalAlignmentDirection | None = None,
) -> AssessmentSignal:
    return AssessmentSignal(
        state=state,
        is_change_from_prior_anchor=is_change_from_prior_anchor,
        alignment_direction=alignment_direction,
        summary="합성 초기 자가 보고 요약",
    )


def _behavior(
    state: BehaviorSignalState = BehaviorSignalState.STABLE,
    *,
    alignment_direction: SignalAlignmentDirection | None = None,
    is_new_pattern: bool = False,
) -> BehaviorSignal:
    return BehaviorSignal(
        state=state,
        alignment_direction=alignment_direction,
        is_new_pattern=is_new_pattern,
        summary="합성 생활 패턴 요약",
    )


def _emotion(
    state: EmotionSignalState = EmotionSignalState.STABLE,
    *,
    alignment_direction: SignalAlignmentDirection | None = None,
) -> EmotionSignal:
    return EmotionSignal(
        state=state,
        alignment_direction=alignment_direction,
        summary="합성 감정 일기 요약",
    )


def test_signal_package_imports_from_repository_root() -> None:
    assert signal_package.combine_signals is combine_signals
    assert signal_package.ReasonCode is ReasonCode
    assert signal_package.SignalAlignmentDirection is SignalAlignmentDirection


def test_all_stable_signals_return_stable_result() -> None:
    result = combine_signals(_assessment(), _behavior(), _emotion())

    assert result.combined_level is CombinedLevel.STABLE
    assert result.result_type is CombinedResultType.ALL_SIGNALS_STABLE
    assert result.reason_codes == []
    assert result.missing_signals == []


def test_elevated_assessment_is_kept_separate_from_stable_recent_signals() -> None:
    result = combine_signals(
        _assessment(AssessmentSignalState.EXHAUSTION_ELEVATED),
        _behavior(),
        _emotion(),
    )

    assert result.combined_level is CombinedLevel.INDETERMINATE
    assert (
        result.result_type
        is CombinedResultType.ASSESSMENT_ELEVATED_WITHOUT_RECENT_CHANGE
    )
    assert ReasonCode.ASSESSMENT_EXHAUSTION_ELEVATED in result.reason_codes
    assert ReasonCode.SELF_REPORT_ELEVATED_WITHOUT_RECENT_CHANGE in result.reason_codes


def test_aligned_recent_behavior_and_emotion_changes_are_explicit() -> None:
    behavior = BehaviorSignal(
        state=BehaviorSignalState.CHANGE_OBSERVED,
        reason_codes=[
            ReasonCode.SLEEP_DECREASE_CONTINUED,
            ReasonCode.ACTIVITY_DECREASE_CONTINUED,
        ],
        top_factors=["sleep_minutes", "active_minutes"],
        is_new_pattern=True,
        alignment_direction=SignalAlignmentDirection.MORE_DIFFICULTY,
        summary="합성 최근 생활 변화 요약",
    )
    result = combine_signals(
        _assessment(),
        behavior,
        _emotion(
            EmotionSignalState.FATIGUE_REPEATED,
            alignment_direction=SignalAlignmentDirection.MORE_DIFFICULTY,
        ),
    )

    assert result.combined_level is CombinedLevel.CHANGE_DETECTED
    assert result.result_type is CombinedResultType.MULTIPLE_SIGNALS_ALIGNED
    assert ReasonCode.NEW_PATTERN_CHANGE in result.reason_codes
    assert ReasonCode.FATIGUE_EXPRESSION_REPEATED in result.reason_codes
    assert ReasonCode.MULTIPLE_SIGNALS_ALIGNED in result.reason_codes


def test_all_three_changed_signals_are_marked_as_aligned() -> None:
    result = combine_signals(
        _assessment(
            AssessmentSignalState.EXHAUSTION_ELEVATED,
            is_change_from_prior_anchor=True,
            alignment_direction=SignalAlignmentDirection.MORE_DIFFICULTY,
        ),
        BehaviorSignal(
            state=BehaviorSignalState.CHANGE_OBSERVED,
            reason_codes=[ReasonCode.REST_DECREASE_CONTINUED],
            top_factors=["rest_minutes"],
            alignment_direction=SignalAlignmentDirection.MORE_DIFFICULTY,
        ),
        _emotion(
            EmotionSignalState.ANXIETY_REPEATED,
            alignment_direction=SignalAlignmentDirection.MORE_DIFFICULTY,
        ),
    )

    assert result.combined_level is CombinedLevel.CHANGE_DETECTED
    assert result.result_type is CombinedResultType.MULTIPLE_SIGNALS_ALIGNED
    assert ReasonCode.MULTIPLE_SIGNALS_ALIGNED in result.reason_codes


def test_change_is_not_new_without_explicit_novelty_metadata() -> None:
    result = combine_signals(
        _assessment(),
        BehaviorSignal(
            state=BehaviorSignalState.CHANGE_OBSERVED,
            reason_codes=[ReasonCode.SLEEP_DECREASE_CONTINUED],
            top_factors=["sleep_minutes"],
            is_new_pattern=False,
        ),
        _emotion(),
    )

    assert (
        result.result_type
        is CombinedResultType.RECENT_CHANGE_WITHOUT_ASSESSMENT_ELEVATION
    )
    assert ReasonCode.SLEEP_DECREASE_CONTINUED in result.reason_codes
    assert ReasonCode.NEW_PATTERN_CHANGE not in result.reason_codes


def test_new_pattern_reason_code_cannot_bypass_explicit_metadata() -> None:
    with pytest.raises(ValidationError, match="supported pattern facts"):
        BehaviorSignal(
            state=BehaviorSignalState.CHANGE_OBSERVED,
            reason_codes=[ReasonCode.NEW_PATTERN_CHANGE],
        )


@pytest.mark.parametrize(
    ("behavior_direction", "emotion_direction"),
    [
        (None, None),
        (
            SignalAlignmentDirection.MORE_DIFFICULTY,
            SignalAlignmentDirection.LESS_DIFFICULTY,
        ),
        (SignalAlignmentDirection.MORE_DIFFICULTY, None),
    ],
)
def test_multiple_signals_without_same_evaluable_direction_are_not_aligned(
    behavior_direction: SignalAlignmentDirection | None,
    emotion_direction: SignalAlignmentDirection | None,
) -> None:
    result = combine_signals(
        _assessment(),
        _behavior(
            BehaviorSignalState.CHANGE_OBSERVED,
            alignment_direction=behavior_direction,
        ),
        _emotion(
            EmotionSignalState.FATIGUE_REPEATED,
            alignment_direction=emotion_direction,
        ),
    )

    assert result.combined_level is CombinedLevel.CHANGE_DETECTED
    assert result.result_type is CombinedResultType.MULTIPLE_SIGNALS_PRESENT
    assert ReasonCode.MULTIPLE_SIGNALS_ALIGNED not in result.reason_codes


@pytest.mark.parametrize(
    ("assessment_direction", "emotion_direction"),
    [
        (None, None),
        (
            SignalAlignmentDirection.MORE_DIFFICULTY,
            SignalAlignmentDirection.LESS_DIFFICULTY,
        ),
    ],
)
def test_assessment_and_recent_change_without_alignment_use_neutral_type(
    assessment_direction: SignalAlignmentDirection | None,
    emotion_direction: SignalAlignmentDirection | None,
) -> None:
    result = combine_signals(
        _assessment(
            AssessmentSignalState.EXHAUSTION_ELEVATED,
            is_change_from_prior_anchor=assessment_direction is not None,
            alignment_direction=assessment_direction,
        ),
        _behavior(),
        _emotion(
            EmotionSignalState.ANXIETY_REPEATED,
            alignment_direction=emotion_direction,
        ),
    )

    assert result.combined_level is CombinedLevel.CHANGE_DETECTED
    assert result.result_type is CombinedResultType.MULTIPLE_SIGNALS_PRESENT
    assert ReasonCode.ASSESSMENT_EXHAUSTION_ELEVATED in result.reason_codes
    assert ReasonCode.ANXIETY_EXPRESSION_REPEATED in result.reason_codes
    assert ReasonCode.MULTIPLE_SIGNALS_ALIGNED not in result.reason_codes


def test_assessment_and_recent_change_with_same_direction_are_aligned() -> None:
    result = combine_signals(
        _assessment(
            AssessmentSignalState.EXHAUSTION_ELEVATED,
            is_change_from_prior_anchor=True,
            alignment_direction=SignalAlignmentDirection.MORE_DIFFICULTY,
        ),
        _behavior(),
        _emotion(
            EmotionSignalState.FATIGUE_REPEATED,
            alignment_direction=SignalAlignmentDirection.MORE_DIFFICULTY,
        ),
    )

    assert result.result_type is CombinedResultType.MULTIPLE_SIGNALS_ALIGNED
    assert ReasonCode.MULTIPLE_SIGNALS_ALIGNED in result.reason_codes


def test_two_same_evaluable_directions_align_even_if_third_differs() -> None:
    result = combine_signals(
        _assessment(
            AssessmentSignalState.EXHAUSTION_ELEVATED,
            is_change_from_prior_anchor=True,
            alignment_direction=SignalAlignmentDirection.LESS_DIFFICULTY,
        ),
        _behavior(
            BehaviorSignalState.CHANGE_OBSERVED,
            alignment_direction=SignalAlignmentDirection.MORE_DIFFICULTY,
        ),
        _emotion(
            EmotionSignalState.ANXIETY_REPEATED,
            alignment_direction=SignalAlignmentDirection.MORE_DIFFICULTY,
        ),
    )

    assert result.result_type is CombinedResultType.MULTIPLE_SIGNALS_ALIGNED
    assert ReasonCode.MULTIPLE_SIGNALS_ALIGNED in result.reason_codes


def test_insufficient_behavior_is_not_treated_as_stable_or_zero() -> None:
    result = combine_signals(
        _assessment(),
        _behavior(BehaviorSignalState.DATA_INSUFFICIENT),
        _emotion(),
    )

    assert result.combined_level is CombinedLevel.INDETERMINATE
    assert result.result_type is CombinedResultType.BEHAVIOR_DATA_INSUFFICIENT
    assert result.missing_signals == [SignalType.BEHAVIOR]
    assert ReasonCode.BEHAVIOR_DATA_INSUFFICIENT in result.reason_codes


def test_health_data_not_connected_is_reported_as_missing() -> None:
    result = combine_signals(
        _assessment(),
        _behavior(BehaviorSignalState.HEALTH_DATA_NOT_CONNECTED),
        _emotion(),
    )

    assert result.combined_level is CombinedLevel.INDETERMINATE
    assert result.result_type is CombinedResultType.HEALTH_DATA_NOT_CONNECTED
    assert result.missing_signals == [SignalType.HEALTH, SignalType.BEHAVIOR]
    assert ReasonCode.HEALTH_DATA_NOT_CONNECTED in result.reason_codes


def test_missing_diary_is_not_treated_as_stable_emotion() -> None:
    result = combine_signals(
        _assessment(),
        _behavior(),
        _emotion(EmotionSignalState.MISSING),
    )

    assert result.combined_level is CombinedLevel.INDETERMINATE
    assert result.result_type is CombinedResultType.EMOTION_DATA_MISSING
    assert result.missing_signals == [SignalType.EMOTION]
    assert ReasonCode.EMOTION_DATA_MISSING in result.reason_codes


def test_multiple_missing_sources_are_all_preserved() -> None:
    result = combine_signals(
        _assessment(),
        _behavior(BehaviorSignalState.HEALTH_DATA_NOT_CONNECTED),
        _emotion(EmotionSignalState.MISSING),
    )

    assert result.combined_level is CombinedLevel.INDETERMINATE
    assert result.result_type is CombinedResultType.HEALTH_DATA_NOT_CONNECTED
    assert result.missing_signals == [
        SignalType.HEALTH,
        SignalType.BEHAVIOR,
        SignalType.EMOTION,
    ]
    assert ReasonCode.HEALTH_DATA_NOT_CONNECTED in result.reason_codes
    assert ReasonCode.EMOTION_DATA_MISSING in result.reason_codes


def test_stable_behavior_rejects_change_only_details() -> None:
    with pytest.raises(ValidationError):
        BehaviorSignal(
            state=BehaviorSignalState.STABLE,
            reason_codes=[ReasonCode.SLEEP_DECREASE_CONTINUED],
            top_factors=["sleep_minutes"],
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "state": BehaviorSignalState.STABLE,
            "is_new_pattern": True,
        },
        {
            "state": BehaviorSignalState.DATA_INSUFFICIENT,
            "alignment_direction": SignalAlignmentDirection.MORE_DIFFICULTY,
        },
    ],
)
def test_non_change_behavior_rejects_change_metadata(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="state=change_observed"):
        BehaviorSignal.model_validate(payload)


def test_fixed_assessment_cannot_claim_directional_alignment() -> None:
    with pytest.raises(
        ValidationError,
        match="is_change_from_prior_anchor",
    ):
        AssessmentSignal(
            state=AssessmentSignalState.EXHAUSTION_ELEVATED,
            alignment_direction=SignalAlignmentDirection.LESS_DIFFICULTY,
        )


@pytest.mark.parametrize(
    "signal",
    [
        {
            "state": AssessmentSignalState.NOT_ELEVATED,
            "alignment_direction": SignalAlignmentDirection.LESS_DIFFICULTY,
        },
        {
            "state": EmotionSignalState.STABLE,
            "alignment_direction": SignalAlignmentDirection.LESS_DIFFICULTY,
        },
        {
            "state": EmotionSignalState.MISSING,
            "alignment_direction": SignalAlignmentDirection.MORE_DIFFICULTY,
        },
    ],
)
def test_inactive_signals_reject_alignment_metadata(
    signal: dict[str, object],
) -> None:
    model = (
        AssessmentSignal
        if isinstance(signal["state"], AssessmentSignalState)
        else EmotionSignal
    )
    with pytest.raises(ValidationError, match="alignment_direction"):
        model.model_validate(signal)
