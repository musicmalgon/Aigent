"""Shared data contracts for the Re:Mind AI foundation.

The models in this module describe self-report anchors, behavioral records,
emotion analysis, and non-diagnostic pattern signals.  They deliberately do
not calculate assessment scores or define medical thresholds.
"""

from __future__ import annotations

import re
import math
import unicodedata
from collections.abc import Mapping
from datetime import date, time
from enum import Enum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    field_validator,
    model_validator,
)


def _reject_non_json_number(value: object) -> object:
    """Reject values JSON Schema would not consider numeric."""

    if isinstance(value, (bool, str, bytes, bytearray)):
        raise ValueError("numeric fields require JSON number values")
    return value


NonEmptyString = Annotated[str, Field(min_length=1)]
JsonInteger = Annotated[int, BeforeValidator(_reject_non_json_number)]
NonNegativeInt = Annotated[JsonInteger, Field(ge=0)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0)]
DayMinutes = Annotated[JsonInteger, Field(ge=0, le=1440)]
Confidence = Annotated[StrictFloat, Field(ge=0, le=1)]
TimeZoneName = Annotated[
    str,
    Field(
        min_length=1,
        pattern=(
            r"^[A-Za-z][A-Za-z0-9._+-]*"
            r"(?:/[A-Za-z0-9][A-Za-z0-9._+-]*)*$"
        ),
    ),
]


class _SchemaModel(BaseModel):
    """Common strict configuration for public schema models."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class AssessmentType(str, Enum):
    """Supported assessment sources.

    ``k_bat`` is a data-contract value only.  Its use remains conditional on
    the separate policy and usage review described in the project docs.
    """

    CUSTOM_INITIAL_STATE_SURVEY = "custom_initial_state_survey"
    K_BAT = "k_bat"


class TargetGroup(str, Enum):
    UNIVERSITY_STUDENT = "university_student"
    JOB_SEEKER = "job_seeker"
    EARLY_CAREER_WORKER = "early_career_worker"


class AssessmentDimension(str, Enum):
    EXHAUSTION = "exhaustion"
    ACADEMIC_BURDEN = "academic_burden"
    OCCUPATIONAL_BURDEN = "occupational_burden"
    RECOVERY_DIFFICULTY = "recovery_difficulty"


class InterpretationScope(str, Enum):
    FIXED_REFERENCE_ONLY = "fixed_reference_only"


class BehavioralMetric(str, Enum):
    SLEEP_MINUTES = "sleep_minutes"
    BEDTIME = "bedtime"
    WAKE_TIME = "wake_time"
    STEPS = "steps"
    ACTIVE_MINUTES = "active_minutes"
    EXERCISE_MINUTES = "exercise_minutes"
    WORK_OR_STUDY_MINUTES = "work_or_study_minutes"
    REST_MINUTES = "rest_minutes"
    SCHEDULE_COUNT = "schedule_count"
    SUBJECTIVE_FATIGUE = "subjective_fatigue"


class BaselineMetric(str, Enum):
    """Numeric behavioral metrics that have unambiguous aggregate values."""

    SLEEP_MINUTES = "sleep_minutes"
    STEPS = "steps"
    ACTIVE_MINUTES = "active_minutes"
    EXERCISE_MINUTES = "exercise_minutes"
    WORK_OR_STUDY_MINUTES = "work_or_study_minutes"
    REST_MINUTES = "rest_minutes"
    SCHEDULE_COUNT = "schedule_count"
    SUBJECTIVE_FATIGUE = "subjective_fatigue"


class DataSource(str, Enum):
    HEALTH_PLATFORM = "health_platform"
    MANUAL = "manual"
    SYNTHETIC = "synthetic"
    NOT_PROVIDED = "not_provided"


class DataCoverage(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class DataSufficiency(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


class MetricSufficiency(str, Enum):
    """Per-metric availability without asserting one global threshold."""

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


class EmotionLabel(str, Enum):
    STABLE = "stable"
    FATIGUE = "fatigue"
    ANXIETY = "anxiety"
    OTHER = "other"


class CoarseEmotionLabel(str, Enum):
    JOY = "기쁨"
    ANXIETY = "불안"
    EMBARRASSMENT = "당황"
    ANGER = "분노"
    SADNESS = "슬픔"
    HURT = "상처"


COARSE_EMOTION_LABELS = tuple(CoarseEmotionLabel)
COARSE_EMOTION_LABEL_TO_ID = {
    label: index for index, label in enumerate(COARSE_EMOTION_LABELS)
}


class UncertaintyReason(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    SMALL_MARGIN = "small_margin"
    LOW_CONFIDENCE_AND_SMALL_MARGIN = "low_confidence_and_small_margin"


class CauseTag(str, Enum):
    SLEEP = "sleep"
    WORKLOAD = "workload"
    ACADEMIC = "academic"
    JOB_SEARCH = "job_search"
    RELATIONSHIP = "relationship"
    DAILY_ROUTINE = "daily_routine"
    UNSPECIFIED = "unspecified"


class ChangeLevel(str, Enum):
    NO_NOTABLE_CHANGE = "no_notable_change"
    CHANGE_OBSERVED = "change_observed"
    UNKNOWN = "unknown"


class ChangeDirection(str, Enum):
    INCREASED = "increased"
    DECREASED = "decreased"
    UNCHANGED = "unchanged"
    UNKNOWN = "unknown"


class MetricUnit(str, Enum):
    MINUTES = "minutes"
    COUNT = "count"
    SCORE = "score"


class CombinedLevel(str, Enum):
    STABLE = "stable"
    CHANGE_DETECTED = "change_detected"
    INDETERMINATE = "indeterminate"


class CombinedResultType(str, Enum):
    ALL_SIGNALS_STABLE = "all_signals_stable"
    ASSESSMENT_ELEVATED_WITHOUT_RECENT_CHANGE = (
        "assessment_elevated_without_recent_change"
    )
    RECENT_CHANGE_WITHOUT_ASSESSMENT_ELEVATION = (
        "recent_change_without_assessment_elevation"
    )
    MULTIPLE_SIGNALS_ALIGNED = "multiple_signals_aligned"
    MULTIPLE_SIGNALS_PRESENT = "multiple_signals_present"
    BEHAVIOR_DATA_INSUFFICIENT = "behavior_data_insufficient"
    HEALTH_DATA_NOT_CONNECTED = "health_data_not_connected"
    EMOTION_DATA_MISSING = "emotion_data_missing"


class ReasonCode(str, Enum):
    ASSESSMENT_EXHAUSTION_ELEVATED = "ASSESSMENT_EXHAUSTION_ELEVATED"
    BEHAVIOR_DATA_INSUFFICIENT = "BEHAVIOR_DATA_INSUFFICIENT"
    HEALTH_DATA_NOT_CONNECTED = "HEALTH_DATA_NOT_CONNECTED"
    SLEEP_DECREASE_CONTINUED = "SLEEP_DECREASE_CONTINUED"
    ACTIVITY_DECREASE_CONTINUED = "ACTIVITY_DECREASE_CONTINUED"
    REST_DECREASE_CONTINUED = "REST_DECREASE_CONTINUED"
    FATIGUE_EXPRESSION_REPEATED = "FATIGUE_EXPRESSION_REPEATED"
    ANXIETY_EXPRESSION_REPEATED = "ANXIETY_EXPRESSION_REPEATED"
    EMOTION_DATA_MISSING = "EMOTION_DATA_MISSING"
    NEW_PATTERN_CHANGE = "NEW_PATTERN_CHANGE"
    MULTIPLE_SIGNALS_ALIGNED = "MULTIPLE_SIGNALS_ALIGNED"
    SELF_REPORT_ELEVATED_WITHOUT_RECENT_CHANGE = (
        "SELF_REPORT_ELEVATED_WITHOUT_RECENT_CHANGE"
    )


class SignalType(str, Enum):
    ASSESSMENT = "assessment"
    BEHAVIOR = "behavior"
    EMOTION = "emotion"
    HEALTH = "health"


class AssessmentAnchor(_SchemaModel):
    """A fixed self-report reference point that AI must not recalculate."""

    assessment_type: AssessmentType
    target_group: TargetGroup
    completed_at: AwareDatetime
    dimensions: Annotated[
        dict[AssessmentDimension, StrictFloat | None],
        Field(min_length=1),
    ]
    interpretation_scope: InterpretationScope
    source: NonEmptyString


class BehavioralDailyRecord(_SchemaModel):
    """One day of behavioral data with field-level provenance and coverage."""

    user_id: NonEmptyString
    date: date
    time_zone: TimeZoneName
    sleep_minutes: DayMinutes | None
    bedtime: time | None
    wake_time: time | None
    steps: NonNegativeInt | None
    active_minutes: DayMinutes | None
    exercise_minutes: DayMinutes | None
    work_or_study_minutes: DayMinutes | None
    rest_minutes: DayMinutes | None
    schedule_count: NonNegativeInt | None
    subjective_fatigue: NonNegativeFloat | None
    source_by_field: Annotated[
        dict[BehavioralMetric, DataSource],
        Field(min_length=1),
    ]
    coverage_by_field: Annotated[
        dict[BehavioralMetric, DataCoverage],
        Field(min_length=1),
    ]

    @field_validator("time_zone", mode="before")
    @classmethod
    def validate_time_zone_wire_value(cls, value: object) -> object:
        if not isinstance(value, str) or value != value.strip():
            raise ValueError("time_zone must be an unpadded IANA time-zone identifier")
        return value

    @field_validator("bedtime", "wake_time", mode="before")
    @classmethod
    def validate_local_time_wire_format(cls, value: object) -> object:
        if value is not None and not isinstance(value, (str, time)):
            raise ValueError(
                "bedtime and wake_time must be HH:MM:SS strings or time objects"
            )
        if (
            isinstance(value, str)
            and re.fullmatch(r"[0-9]{2}:[0-9]{2}:[0-9]{2}", value) is None
        ):
            raise ValueError("bedtime and wake_time strings must use HH:MM:SS")
        return value

    @field_validator("bedtime", "wake_time")
    @classmethod
    def validate_local_clock_time(cls, value: time | None) -> time | None:
        if value is not None and (
            value.utcoffset() is not None or value.microsecond != 0
        ):
            raise ValueError(
                "bedtime and wake_time must be whole-second local times "
                "without a UTC offset"
            )
        return value

    @model_validator(mode="after")
    def validate_field_metadata(self) -> "BehavioralDailyRecord":
        """Keep nullable values consistent with field-level coverage metadata."""

        source_fields = set(self.source_by_field)
        coverage_fields = set(self.coverage_by_field)
        expected_fields = set(BehavioralMetric)
        if source_fields != expected_fields:
            raise ValueError(
                "source_by_field must describe every BehavioralMetric field"
            )
        if coverage_fields != expected_fields:
            raise ValueError(
                "coverage_by_field must describe every BehavioralMetric field"
            )

        for metric in coverage_fields:
            value = getattr(self, metric.value)
            coverage = self.coverage_by_field[metric]
            source = self.source_by_field[metric]

            if coverage is DataCoverage.UNAVAILABLE and value is not None:
                raise ValueError(
                    f"{metric.value} must be null when coverage is unavailable"
                )
            if value is None and coverage is not DataCoverage.UNAVAILABLE:
                raise ValueError(
                    f"{metric.value} requires unavailable coverage when it is null"
                )
            if source is DataSource.NOT_PROVIDED and value is not None:
                raise ValueError(
                    f"{metric.value} must be null when its source is not_provided"
                )

        return self


MetricValues = dict[BaselineMetric, NonNegativeFloat | None]
MetricValidDays = dict[BaselineMetric, NonNegativeInt]
MetricSufficiencyMap = dict[BaselineMetric, MetricSufficiency]


class BehavioralBaseline(_SchemaModel):
    """Descriptive baseline aggregates; no clinical thresholds are encoded."""

    baseline_start: date
    baseline_end: date
    valid_days: NonNegativeInt
    valid_days_by_metric: Annotated[MetricValidDays, Field(min_length=1)]
    minimum_required_days: Annotated[JsonInteger, Field(ge=1)]
    sufficiency_by_metric: Annotated[
        MetricSufficiencyMap,
        Field(min_length=1),
    ]
    data_sufficiency: DataSufficiency
    averages: MetricValues
    medians: MetricValues
    weekday_averages: MetricValues
    weekend_averages: MetricValues
    calculation_version: NonEmptyString

    @model_validator(mode="after")
    def validate_period_and_sufficiency(self) -> "BehavioralBaseline":
        if self.baseline_end < self.baseline_start:
            raise ValueError("baseline_end must not precede baseline_start")

        period_days = (self.baseline_end - self.baseline_start).days + 1
        if self.valid_days > period_days:
            raise ValueError("valid_days must not exceed the baseline period")
        if (
            self.data_sufficiency is DataSufficiency.SUFFICIENT
            and self.valid_days < self.minimum_required_days
        ):
            raise ValueError("sufficient data requires at least minimum_required_days")
        if (
            self.data_sufficiency is DataSufficiency.INSUFFICIENT
            and self.valid_days >= self.minimum_required_days
        ):
            raise ValueError(
                "insufficient data requires fewer than minimum_required_days"
            )
        if (
            self.data_sufficiency is DataSufficiency.UNAVAILABLE
            and self.valid_days != 0
        ):
            raise ValueError("unavailable data requires valid_days=0")

        metric_keys = set(self.valid_days_by_metric)
        if metric_keys != set(self.sufficiency_by_metric):
            raise ValueError(
                "valid_days_by_metric and sufficiency_by_metric must use "
                "the same metric keys"
            )

        summary_maps: dict[
            str,
            Mapping[BaselineMetric, float | None],
        ] = {
            "averages": self.averages,
            "medians": self.medians,
            "weekday_averages": self.weekday_averages,
            "weekend_averages": self.weekend_averages,
        }
        for field_name, values in summary_maps.items():
            if not set(values).issubset(metric_keys):
                raise ValueError(
                    f"{field_name} cannot contain a metric without valid-day metadata"
                )

        for metric in metric_keys:
            valid_days = self.valid_days_by_metric[metric]
            sufficiency = self.sufficiency_by_metric[metric]
            if valid_days > period_days or valid_days > self.valid_days:
                raise ValueError(
                    f"{metric.value} valid days must not exceed the "
                    "baseline period or overall valid_days"
                )

            if sufficiency is MetricSufficiency.UNAVAILABLE and valid_days != 0:
                raise ValueError(
                    f"{metric.value} unavailable data requires 0 valid days"
                )
            if (
                sufficiency
                in {
                    MetricSufficiency.SUFFICIENT,
                    MetricSufficiency.PARTIAL,
                }
                and valid_days == 0
            ):
                raise ValueError(
                    f"{metric.value} sufficient or partial data requires "
                    "at least 1 valid day"
                )

            summary_values = tuple(
                values.get(metric) for values in summary_maps.values()
            )
            if valid_days == 0 and any(value is not None for value in summary_values):
                raise ValueError(
                    f"{metric.value} summaries must be null when valid days are 0"
                )

        return self


class EmotionAnalysis(_SchemaModel):
    """A non-diagnostic emotion classification result."""

    primary_emotion: EmotionLabel
    secondary_signals: list[EmotionLabel]
    confidence: Confidence
    cause_tags: list[CauseTag]
    sleep_related: StrictBool | None
    workload_related: StrictBool | None
    model_name: NonEmptyString
    model_version: NonEmptyString

    @model_validator(mode="after")
    def validate_labels(self) -> "EmotionAnalysis":
        if len(set(self.secondary_signals)) != len(self.secondary_signals):
            raise ValueError("secondary_signals must not contain duplicates")
        if self.primary_emotion in self.secondary_signals:
            raise ValueError(
                "primary_emotion must not be repeated in secondary_signals"
            )
        if len(set(self.cause_tags)) != len(self.cause_tags):
            raise ValueError("cause_tags must not contain duplicates")
        return self


def _normalize_utterance(value: object, *, optional: bool) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError("utterances must be strings")
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFC", value).strip())
    if not normalized:
        if optional:
            return None
        raise ValueError("required utterances must not be empty")
    return normalized


class CoarseEmotionInput(_SchemaModel):
    """Up to three user turns matching the coarse model training input."""

    hs01: Annotated[str, Field(min_length=1, max_length=2000)]
    hs02: Annotated[str, Field(min_length=1, max_length=2000)]
    hs03: Annotated[str, Field(min_length=1, max_length=2000)] | None = None

    @field_validator("hs01", "hs02", mode="before")
    @classmethod
    def normalize_required_utterance(cls, value: object) -> str:
        normalized = _normalize_utterance(value, optional=False)
        assert isinstance(normalized, str)
        return normalized

    @field_validator("hs03", mode="before")
    @classmethod
    def normalize_optional_utterance(cls, value: object) -> str | None:
        return _normalize_utterance(value, optional=True)


class CoarseEmotionTopPrediction(_SchemaModel):
    emotion: CoarseEmotionLabel
    label_id: Annotated[JsonInteger, Field(ge=0, le=5)]
    probability: Confidence

    @model_validator(mode="after")
    def validate_label_id(self) -> "CoarseEmotionTopPrediction":
        if self.label_id != COARSE_EMOTION_LABEL_TO_ID[self.emotion]:
            raise ValueError("label_id does not match emotion")
        return self


class CoarseEmotionInferenceResponse(_SchemaModel):
    """Non-diagnostic six-class model output suitable for trend aggregation."""

    model_version: NonEmptyString
    predicted_emotion: CoarseEmotionLabel
    predicted_label_id: Annotated[JsonInteger, Field(ge=0, le=5)]
    confidence: Confidence
    is_uncertain: StrictBool
    uncertainty_reason: UncertaintyReason | None
    probabilities: Annotated[
        dict[CoarseEmotionLabel, Confidence],
        Field(min_length=6, max_length=6),
    ]
    top_predictions: Annotated[
        list[CoarseEmotionTopPrediction],
        Field(min_length=1, max_length=6),
    ]
    latency_ms: NonNegativeFloat

    @model_validator(mode="after")
    def validate_prediction_consistency(self) -> "CoarseEmotionInferenceResponse":
        if set(self.probabilities) != set(COARSE_EMOTION_LABELS):
            raise ValueError("probabilities must contain exactly the six coarse labels")
        probability_sum = sum(self.probabilities.values())
        if not math.isclose(probability_sum, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("probabilities must sum to one")

        ordered = sorted(
            self.probabilities.items(),
            key=lambda item: (-item[1], COARSE_EMOTION_LABEL_TO_ID[item[0]]),
        )
        winner, winner_probability = ordered[0]
        if self.predicted_emotion is not winner:
            raise ValueError("predicted_emotion must be the maximum probability label")
        if self.predicted_label_id != COARSE_EMOTION_LABEL_TO_ID[winner]:
            raise ValueError("predicted_label_id does not match predicted_emotion")
        if not math.isclose(
            self.confidence,
            winner_probability,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise ValueError("confidence must equal the maximum probability")

        if len({item.emotion for item in self.top_predictions}) != len(
            self.top_predictions
        ):
            raise ValueError("top_predictions must not contain duplicates")
        for index, prediction in enumerate(self.top_predictions):
            expected_label, expected_probability = ordered[index]
            if prediction.emotion is not expected_label or not math.isclose(
                prediction.probability,
                expected_probability,
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise ValueError("top_predictions must be sorted by probability")

        if self.is_uncertain != (self.uncertainty_reason is not None):
            raise ValueError("uncertainty_reason must match is_uncertain")
        return self


class PatternFactor(_SchemaModel):
    """One descriptive factor contributing to an observed pattern change."""

    metric: BaselineMetric
    direction: ChangeDirection
    baseline_value: NonNegativeFloat | None
    recent_value: NonNegativeFloat | None
    change_amount: StrictFloat | None
    unit: MetricUnit


class PatternChangeResult(_SchemaModel):
    """A descriptive recent-pattern comparison result."""

    data_sufficiency: DataSufficiency
    change_level: ChangeLevel
    duration_days: NonNegativeInt | None
    factors: list[PatternFactor]
    calculation_version: NonEmptyString

    @model_validator(mode="after")
    def validate_result_state(self) -> "PatternChangeResult":
        if self.data_sufficiency is not DataSufficiency.SUFFICIENT:
            if (
                self.change_level is not ChangeLevel.UNKNOWN
                or self.duration_days is not None
                or self.factors
            ):
                raise ValueError(
                    "insufficient or unavailable data requires unknown change, "
                    "null duration, and no factors"
                )
            return self

        if self.change_level is ChangeLevel.NO_NOTABLE_CHANGE:
            if self.duration_days != 0 or self.factors:
                raise ValueError(
                    "no notable change requires duration_days=0 and no factors"
                )
            return self

        if self.change_level is ChangeLevel.CHANGE_OBSERVED:
            if self.duration_days is None or self.duration_days < 1:
                raise ValueError("observed change requires a positive duration_days")
            if not self.factors:
                raise ValueError("observed change requires at least one factor")
            return self

        raise ValueError("sufficient data cannot use change_level=unknown")


class CombinedSignalResult(_SchemaModel):
    """A rule-based combination result without diagnosis or probability."""

    combined_level: CombinedLevel
    result_type: CombinedResultType
    reason_codes: list[ReasonCode]
    top_factors: list[NonEmptyString]
    missing_signals: list[SignalType]
    assessment_summary: NonEmptyString | None
    behavior_summary: NonEmptyString | None
    emotion_summary: NonEmptyString | None
    rule_version: NonEmptyString

    @model_validator(mode="after")
    def validate_unique_codes_and_signals(self) -> "CombinedSignalResult":
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must not contain duplicates")
        if len(set(self.missing_signals)) != len(self.missing_signals):
            raise ValueError("missing_signals must not contain duplicates")

        reason_codes = set(self.reason_codes)
        missing_signals = set(self.missing_signals)
        is_stable_level = self.combined_level is CombinedLevel.STABLE
        is_stable_result = self.result_type is CombinedResultType.ALL_SIGNALS_STABLE
        if is_stable_level != is_stable_result:
            raise ValueError(
                "stable combined_level and all_signals_stable result_type "
                "must be used together"
            )
        if is_stable_result and (
            self.reason_codes or self.top_factors or self.missing_signals
        ):
            raise ValueError(
                "all_signals_stable cannot contain reasons, factors, or missing signals"
            )

        indeterminate_contracts: dict[
            CombinedResultType,
            tuple[set[ReasonCode], set[SignalType]],
        ] = {
            CombinedResultType.ASSESSMENT_ELEVATED_WITHOUT_RECENT_CHANGE: (
                {
                    ReasonCode.ASSESSMENT_EXHAUSTION_ELEVATED,
                    ReasonCode.SELF_REPORT_ELEVATED_WITHOUT_RECENT_CHANGE,
                },
                set(),
            ),
            CombinedResultType.BEHAVIOR_DATA_INSUFFICIENT: (
                {ReasonCode.BEHAVIOR_DATA_INSUFFICIENT},
                {SignalType.BEHAVIOR},
            ),
            CombinedResultType.HEALTH_DATA_NOT_CONNECTED: (
                {ReasonCode.HEALTH_DATA_NOT_CONNECTED},
                {SignalType.HEALTH, SignalType.BEHAVIOR},
            ),
            CombinedResultType.EMOTION_DATA_MISSING: (
                {ReasonCode.EMOTION_DATA_MISSING},
                {SignalType.EMOTION},
            ),
        }
        if self.result_type in indeterminate_contracts:
            required_reasons, required_missing = indeterminate_contracts[
                self.result_type
            ]
            if self.combined_level is not CombinedLevel.INDETERMINATE:
                raise ValueError(
                    "missing-data and fixed-assessment results require "
                    "combined_level=indeterminate"
                )
            if not required_reasons.issubset(reason_codes):
                raise ValueError(
                    f"{self.result_type.value} lacks its required reason codes"
                )
            if not required_missing.issubset(missing_signals):
                raise ValueError(
                    f"{self.result_type.value} lacks its required missing signals"
                )
            if (
                self.result_type
                is CombinedResultType.ASSESSMENT_ELEVATED_WITHOUT_RECENT_CHANGE
                and missing_signals
            ):
                raise ValueError(
                    "assessment_elevated_without_recent_change cannot "
                    "contain missing_signals"
                )

        recent_result_types = {
            CombinedResultType.RECENT_CHANGE_WITHOUT_ASSESSMENT_ELEVATION,
            CombinedResultType.MULTIPLE_SIGNALS_ALIGNED,
            CombinedResultType.MULTIPLE_SIGNALS_PRESENT,
        }
        if self.result_type in recent_result_types:
            if self.combined_level is not CombinedLevel.CHANGE_DETECTED:
                raise ValueError(
                    "recent signal results require combined_level=change_detected"
                )
            if missing_signals:
                raise ValueError("recent signal results cannot contain missing_signals")

        if (
            self.result_type is CombinedResultType.MULTIPLE_SIGNALS_ALIGNED
            and ReasonCode.MULTIPLE_SIGNALS_ALIGNED not in reason_codes
        ):
            raise ValueError(
                "multiple_signals_aligned requires its alignment reason code"
            )
        if (
            self.result_type is CombinedResultType.MULTIPLE_SIGNALS_PRESENT
            and ReasonCode.MULTIPLE_SIGNALS_ALIGNED in reason_codes
        ):
            raise ValueError("multiple_signals_present cannot claim aligned signals")
        return self


__all__ = [
    "AssessmentAnchor",
    "AssessmentDimension",
    "AssessmentType",
    "BaselineMetric",
    "BehavioralBaseline",
    "BehavioralDailyRecord",
    "BehavioralMetric",
    "CauseTag",
    "ChangeDirection",
    "ChangeLevel",
    "CombinedLevel",
    "CombinedResultType",
    "CombinedSignalResult",
    "CoarseEmotionInferenceResponse",
    "CoarseEmotionInput",
    "CoarseEmotionLabel",
    "CoarseEmotionTopPrediction",
    "DataCoverage",
    "DataSource",
    "DataSufficiency",
    "EmotionAnalysis",
    "EmotionLabel",
    "InterpretationScope",
    "MetricSufficiency",
    "MetricUnit",
    "PatternChangeResult",
    "PatternFactor",
    "ReasonCode",
    "SignalType",
    "TargetGroup",
    "UncertaintyReason",
]
