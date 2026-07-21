"""Conservative skeleton for combining pre-interpreted Re:Mind signals.

This module intentionally does not inspect or recalculate assessment scores,
derive behavioral thresholds, or apply weighted probabilities. Each input
state must be produced by its owning, versioned policy before it reaches this
combiner.
"""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Annotated, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from ..schemas import (
    CombinedLevel,
    CombinedResultType,
    CombinedSignalResult,
    ReasonCode,
    SignalType,
)


NonEmptyString = Annotated[str, Field(min_length=1)]
ItemType = TypeVar("ItemType")


class _SignalInput(BaseModel):
    """Strict base class for already interpreted signal summaries."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class AssessmentSignalState(str, Enum):
    """Assessment state supplied by the assessment owner's policy."""

    NOT_ELEVATED = "not_elevated"
    EXHAUSTION_ELEVATED = "exhaustion_elevated"


class BehaviorSignalState(str, Enum):
    """Behavior state supplied by a future pattern-comparison module."""

    STABLE = "stable"
    CHANGE_OBSERVED = "change_observed"
    DATA_INSUFFICIENT = "data_insufficient"
    HEALTH_DATA_NOT_CONNECTED = "health_data_not_connected"


class EmotionSignalState(str, Enum):
    """Diary aggregation state supplied without choosing a numeric threshold."""

    STABLE = "stable"
    FATIGUE_REPEATED = "fatigue_repeated"
    ANXIETY_REPEATED = "anxiety_repeated"
    FATIGUE_AND_ANXIETY_REPEATED = "fatigue_and_anxiety_repeated"
    MISSING = "missing"


class SignalAlignmentDirection(str, Enum):
    """Normalized, non-medical direction supplied by an owning policy.

    This direction is not the raw sign of a metric. For example, reduced sleep
    and increased fatigue expressions can both be normalized to
    ``more_difficulty`` only after their separate policies have enough evidence
    to make that comparison. ``None`` means that alignment was not evaluated.
    """

    MORE_DIFFICULTY = "more_difficulty"
    LESS_DIFFICULTY = "less_difficulty"


class AssessmentSignal(_SignalInput):
    """Assessment state plus explicitly evidenced comparative metadata."""

    state: AssessmentSignalState
    is_change_from_prior_anchor: StrictBool = Field(
        default=False,
        description=(
            "True only when a versioned assessment policy compared this "
            "state with a prior anchor and established a directional change"
        ),
    )
    alignment_direction: SignalAlignmentDirection | None = None
    summary: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_alignment_metadata(self) -> "AssessmentSignal":
        if (
            self.state is AssessmentSignalState.NOT_ELEVATED
            and self.alignment_direction is not None
        ):
            raise ValueError(
                "assessment alignment_direction requires an elevated state"
            )
        if self.is_change_from_prior_anchor != (self.alignment_direction is not None):
            raise ValueError(
                "assessment alignment_direction requires explicit "
                "is_change_from_prior_anchor evidence"
            )
        return self


class BehaviorSignal(_SignalInput):
    """Pattern state and factors determined by a separate comparison policy."""

    state: BehaviorSignalState
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    top_factors: list[NonEmptyString] = Field(default_factory=list)
    is_new_pattern: StrictBool = Field(
        default=False,
        description=(
            "True only when the owning comparison policy explicitly established "
            "novelty; false does not prove that a pattern is old"
        ),
    )
    alignment_direction: SignalAlignmentDirection | None = None
    summary: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_change_details(self) -> "BehaviorSignal":
        allowed_reason_codes = {
            ReasonCode.SLEEP_DECREASE_CONTINUED,
            ReasonCode.ACTIVITY_DECREASE_CONTINUED,
            ReasonCode.REST_DECREASE_CONTINUED,
        }
        unsupported_codes = set(self.reason_codes) - allowed_reason_codes
        if unsupported_codes:
            raise ValueError(
                "behavior reason_codes must describe supported pattern facts"
            )
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("behavior reason_codes must not contain duplicates")
        if len(set(self.top_factors)) != len(self.top_factors):
            raise ValueError("behavior top_factors must not contain duplicates")
        if self.state is not BehaviorSignalState.CHANGE_OBSERVED and (
            self.reason_codes
            or self.top_factors
            or self.is_new_pattern
            or self.alignment_direction is not None
        ):
            raise ValueError("behavior details require state=change_observed")
        return self


class EmotionSignal(_SignalInput):
    """Aggregated diary state plus an optional source-preserving summary."""

    state: EmotionSignalState
    alignment_direction: SignalAlignmentDirection | None = None
    summary: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_alignment_metadata(self) -> "EmotionSignal":
        if (
            self.state
            in {
                EmotionSignalState.STABLE,
                EmotionSignalState.MISSING,
            }
            and self.alignment_direction is not None
        ):
            raise ValueError(
                "emotion alignment_direction requires a repeated emotion state"
            )
        return self


def _append_unique(items: list[ItemType], value: ItemType) -> None:
    if value not in items:
        items.append(value)


def _collect_available_signal_details(
    assessment: AssessmentSignal,
    behavior: BehaviorSignal,
    emotion: EmotionSignal,
) -> tuple[
    list[ReasonCode],
    list[str],
    int,
    list[SignalAlignmentDirection],
]:
    """Collect explicit facts without scoring or comparing their magnitudes."""

    reason_codes: list[ReasonCode] = []
    top_factors: list[str] = []
    present_signal_count = 0
    alignment_directions: list[SignalAlignmentDirection] = []

    if assessment.state is AssessmentSignalState.EXHAUSTION_ELEVATED:
        present_signal_count += 1
        _append_unique(
            reason_codes,
            ReasonCode.ASSESSMENT_EXHAUSTION_ELEVATED,
        )
        _append_unique(top_factors, "assessment.exhaustion")
        if (
            assessment.is_change_from_prior_anchor
            and assessment.alignment_direction is not None
        ):
            alignment_directions.append(assessment.alignment_direction)

    if behavior.state is BehaviorSignalState.CHANGE_OBSERVED:
        present_signal_count += 1
        if behavior.is_new_pattern:
            _append_unique(reason_codes, ReasonCode.NEW_PATTERN_CHANGE)
        for reason_code in behavior.reason_codes:
            _append_unique(reason_codes, reason_code)
        for factor in behavior.top_factors:
            _append_unique(top_factors, factor)
        if behavior.alignment_direction is not None:
            alignment_directions.append(behavior.alignment_direction)

    if emotion.state in {
        EmotionSignalState.FATIGUE_REPEATED,
        EmotionSignalState.FATIGUE_AND_ANXIETY_REPEATED,
    }:
        _append_unique(
            reason_codes,
            ReasonCode.FATIGUE_EXPRESSION_REPEATED,
        )
        _append_unique(top_factors, "emotion.fatigue")

    if emotion.state in {
        EmotionSignalState.ANXIETY_REPEATED,
        EmotionSignalState.FATIGUE_AND_ANXIETY_REPEATED,
    }:
        _append_unique(
            reason_codes,
            ReasonCode.ANXIETY_EXPRESSION_REPEATED,
        )
        _append_unique(top_factors, "emotion.anxiety")

    if emotion.state not in {
        EmotionSignalState.STABLE,
        EmotionSignalState.MISSING,
    }:
        present_signal_count += 1
        if emotion.alignment_direction is not None:
            alignment_directions.append(emotion.alignment_direction)

    return (
        reason_codes,
        top_factors,
        present_signal_count,
        alignment_directions,
    )


def _has_aligned_evaluable_signals(
    alignment_directions: list[SignalAlignmentDirection],
) -> bool:
    """Return whether at least two evaluated signals share one direction."""

    direction_counts = Counter(alignment_directions)
    return any(count >= 2 for count in direction_counts.values())


def combine_signals(
    assessment: AssessmentSignal,
    behavior: BehaviorSignal,
    emotion: EmotionSignal,
    *,
    rule_version: NonEmptyString = "foundation-skeleton-v2",
) -> CombinedSignalResult:
    """Combine explicit signal states without weights or diagnostic output.

    Missing behavior or emotion data takes precedence in ``result_type`` so a
    caller cannot mistake unavailable evidence for a stable observation.
    Available reason codes are still preserved for traceability. This function
    does not infer novelty or direction: ``NEW_PATTERN_CHANGE`` requires an
    explicit ``is_new_pattern=True``, while alignment requires at least two
    non-null, identical ``alignment_direction`` values. An Assessment
    direction additionally requires explicit prior-anchor comparison evidence;
    a fixed elevated state alone is never treated as a directional change.
    """

    (
        reason_codes,
        top_factors,
        present_signal_count,
        alignment_directions,
    ) = _collect_available_signal_details(assessment, behavior, emotion)
    missing_signals: list[SignalType] = []

    if behavior.state is BehaviorSignalState.HEALTH_DATA_NOT_CONNECTED:
        _append_unique(reason_codes, ReasonCode.HEALTH_DATA_NOT_CONNECTED)
        _append_unique(missing_signals, SignalType.HEALTH)
        _append_unique(missing_signals, SignalType.BEHAVIOR)
    elif behavior.state is BehaviorSignalState.DATA_INSUFFICIENT:
        _append_unique(reason_codes, ReasonCode.BEHAVIOR_DATA_INSUFFICIENT)
        _append_unique(missing_signals, SignalType.BEHAVIOR)

    if emotion.state is EmotionSignalState.MISSING:
        _append_unique(reason_codes, ReasonCode.EMOTION_DATA_MISSING)
        _append_unique(missing_signals, SignalType.EMOTION)

    if missing_signals:
        if SignalType.HEALTH in missing_signals:
            result_type = CombinedResultType.HEALTH_DATA_NOT_CONNECTED
        elif SignalType.BEHAVIOR in missing_signals:
            result_type = CombinedResultType.BEHAVIOR_DATA_INSUFFICIENT
        else:
            result_type = CombinedResultType.EMOTION_DATA_MISSING

        return CombinedSignalResult(
            combined_level=CombinedLevel.INDETERMINATE,
            result_type=result_type,
            reason_codes=reason_codes,
            top_factors=top_factors,
            missing_signals=missing_signals,
            assessment_summary=assessment.summary,
            behavior_summary=behavior.summary,
            emotion_summary=emotion.summary,
            rule_version=rule_version,
        )

    recent_change_present = (
        behavior.state is BehaviorSignalState.CHANGE_OBSERVED
        or emotion.state
        not in {
            EmotionSignalState.STABLE,
            EmotionSignalState.MISSING,
        }
    )
    has_aligned_signals = _has_aligned_evaluable_signals(alignment_directions)

    if present_signal_count == 0:
        combined_level = CombinedLevel.STABLE
        result_type = CombinedResultType.ALL_SIGNALS_STABLE
    elif (
        assessment.state is AssessmentSignalState.EXHAUSTION_ELEVATED
        and not recent_change_present
    ):
        combined_level = CombinedLevel.INDETERMINATE
        result_type = CombinedResultType.ASSESSMENT_ELEVATED_WITHOUT_RECENT_CHANGE
        _append_unique(
            reason_codes,
            ReasonCode.SELF_REPORT_ELEVATED_WITHOUT_RECENT_CHANGE,
        )
    elif has_aligned_signals:
        combined_level = CombinedLevel.CHANGE_DETECTED
        result_type = CombinedResultType.MULTIPLE_SIGNALS_ALIGNED
        _append_unique(reason_codes, ReasonCode.MULTIPLE_SIGNALS_ALIGNED)
    elif present_signal_count >= 2:
        combined_level = CombinedLevel.CHANGE_DETECTED
        result_type = CombinedResultType.MULTIPLE_SIGNALS_PRESENT
    else:
        combined_level = CombinedLevel.CHANGE_DETECTED
        result_type = CombinedResultType.RECENT_CHANGE_WITHOUT_ASSESSMENT_ELEVATION

    return CombinedSignalResult(
        combined_level=combined_level,
        result_type=result_type,
        reason_codes=reason_codes,
        top_factors=top_factors,
        missing_signals=missing_signals,
        assessment_summary=assessment.summary,
        behavior_summary=behavior.summary,
        emotion_summary=emotion.summary,
        rule_version=rule_version,
    )


__all__ = [
    "AssessmentSignal",
    "AssessmentSignalState",
    "BehaviorSignal",
    "BehaviorSignalState",
    "EmotionSignal",
    "EmotionSignalState",
    "SignalAlignmentDirection",
    "combine_signals",
]
