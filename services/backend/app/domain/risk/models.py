"""Validated public models for burnout risk rules v1."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    model_validator,
)


def _reject_non_json_number(value: object) -> object:
    if isinstance(value, (bool, str, bytes, bytearray)):
        raise ValueError("numeric fields require JSON number values")
    return value


NonNegativeNumber = Annotated[
    float,
    BeforeValidator(_reject_non_json_number),
    Field(ge=0),
]
DayMinutes = Annotated[
    float,
    BeforeValidator(_reject_non_json_number),
    Field(ge=0, le=1440),
]
Probability = Annotated[
    float,
    BeforeValidator(_reject_non_json_number),
    Field(ge=0, le=1),
]
SubjectiveRating = Annotated[
    float,
    BeforeValidator(_reject_non_json_number),
    Field(ge=0, le=10),
]
Score = Annotated[
    float,
    BeforeValidator(_reject_non_json_number),
    Field(ge=0, le=100),
]
NonNegativeInteger = Annotated[
    int,
    BeforeValidator(_reject_non_json_number),
    Field(ge=0),
]


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        frozen=True,
    )


class RiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class BaselineStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT = "insufficient"
    MISSING = "missing"


class DataQuality(StrEnum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


class RiskCategory(StrEnum):
    SLEEP = "sleep"
    WORKLOAD = "workload"
    RECOVERY = "recovery"
    EMOTION = "emotion"
    SUBJECTIVE = "subjective"


class FactorCategory(StrEnum):
    SLEEP = "sleep"
    WORKLOAD = "workload"
    RECOVERY = "recovery"
    EMOTION = "emotion"
    SUBJECTIVE = "subjective"
    DATA_QUALITY = "data_quality"


class FactorKind(StrEnum):
    RISK = "risk"
    INFORMATIONAL = "informational"


class FactorCode(StrEnum):
    SLEEP_DECREASE = "sleep_decrease"
    WORKLOAD_INCREASE = "workload_increase"
    SCHEDULE_OVERLOAD = "schedule_overload"
    REST_DECREASE = "rest_decrease"
    EXERCISE_DECREASE = "exercise_decrease"
    NEGATIVE_EMOTION_INCREASE = "negative_emotion_increase"
    HIGH_NEGATIVE_EMOTION = "high_negative_emotion"
    SUBJECTIVE_STRESS = "subjective_stress"
    SUBJECTIVE_FATIGUE = "subjective_fatigue"
    INSUFFICIENT_BASELINE = "insufficient_baseline"
    INSUFFICIENT_DATA = "insufficient_data"


class EmotionProbabilities(_ContractModel):
    joy: Probability = Field(alias="기쁨")
    anxiety: Probability = Field(alias="불안")
    embarrassment: Probability = Field(alias="당황")
    anger: Probability = Field(alias="분노")
    sadness: Probability = Field(alias="슬픔")
    lethargy: Probability = Field(alias="무기력")

    @model_validator(mode="after")
    def validate_probability_sum(self) -> EmotionProbabilities:
        if abs(sum(self.as_tuple()) - 1.0) > 1e-6:
            raise ValueError("emotion probabilities must sum to 1 within 0.000001")
        return self

    def as_tuple(self) -> tuple[float, ...]:
        return (
            self.joy,
            self.anxiety,
            self.embarrassment,
            self.anger,
            self.sadness,
            self.lethargy,
        )

    @property
    def negative_probability(self) -> float:
        return 1.0 - self.joy


class CurrentRiskSignals(_ContractModel):
    sleep_minutes: DayMinutes | None = None
    work_or_study_minutes: DayMinutes | None = None
    rest_minutes: DayMinutes | None = None
    exercise_minutes: DayMinutes | None = None
    schedule_count: NonNegativeInteger | None = None
    subjective_stress: SubjectiveRating | None = None
    subjective_fatigue: NonNegativeNumber | None = None
    emotion_probabilities: EmotionProbabilities | None = None
    emotion_confidence: Probability | None = None
    emotion_uncertain: StrictBool | None = None

    @model_validator(mode="after")
    def validate_emotion_metadata(self) -> CurrentRiskSignals:
        if self.emotion_probabilities is None and (
            self.emotion_confidence is not None
            or self.emotion_uncertain is not None
        ):
            raise ValueError(
                "emotion confidence and uncertainty require probabilities"
            )
        return self


class PersonalBaseline(_ContractModel):
    sleep_minutes: DayMinutes | None = None
    work_or_study_minutes: DayMinutes | None = None
    rest_minutes: DayMinutes | None = None
    exercise_minutes: DayMinutes | None = None
    schedule_count: NonNegativeNumber | None = None
    subjective_stress: SubjectiveRating | None = None
    subjective_fatigue: NonNegativeNumber | None = None
    negative_emotion_probability: Probability | None = None
    sample_days: NonNegativeInteger


class BurnoutRiskEvaluationRequest(_ContractModel):
    current: CurrentRiskSignals
    baseline: PersonalBaseline | None = None


class RiskFactor(_ContractModel):
    code: FactorCode
    category: FactorCategory
    kind: FactorKind
    severity: Probability
    weight: Probability
    contribution: Score
    observed_value: NonNegativeNumber | None
    baseline_value: NonNegativeNumber | None
    change_percent: float | None
    message_key: Annotated[str, Field(min_length=1, pattern=r"^risk\.")]

    @model_validator(mode="after")
    def validate_factor_kind(self) -> RiskFactor:
        if self.kind is FactorKind.INFORMATIONAL and (
            self.severity != 0 or self.weight != 0 or self.contribution != 0
        ):
            raise ValueError("informational factors cannot contribute to score")
        if self.kind is FactorKind.RISK and self.contribution <= 0:
            raise ValueError("risk factors must have a positive contribution")
        return self


class RiskSummary(_ContractModel):
    top_factor_codes: list[FactorCode]
    available_signal_count: Annotated[int, Field(ge=0, le=7)]
    missing_signal_count: Annotated[int, Field(ge=0, le=7)]
    available_category_count: Annotated[int, Field(ge=0, le=5)]
    missing_category_count: Annotated[int, Field(ge=0, le=5)]

    @model_validator(mode="after")
    def validate_counts(self) -> RiskSummary:
        if self.available_signal_count + self.missing_signal_count != 7:
            raise ValueError("available and missing signal counts must total 7")
        if self.available_category_count + self.missing_category_count != 5:
            raise ValueError("available and missing category counts must total 5")
        if len(self.top_factor_codes) > 3:
            raise ValueError("at most three top factor codes are allowed")
        if len(set(self.top_factor_codes)) != len(self.top_factor_codes):
            raise ValueError("top factor codes must be unique")
        return self


class BurnoutRiskEvaluationResponse(_ContractModel):
    score: Score
    level: RiskLevel
    is_provisional: StrictBool
    baseline_status: BaselineStatus
    data_quality: DataQuality
    category_scores: dict[RiskCategory, Score]
    factors: list[RiskFactor]
    summary: RiskSummary
    engine_version: Literal["burnout-risk-rules-v1"]

    @model_validator(mode="after")
    def validate_result_invariants(self) -> BurnoutRiskEvaluationResponse:
        expected_order = sorted(
            self.factors,
            key=lambda item: (-item.contribution, item.code.value),
        )
        if self.factors != expected_order:
            raise ValueError("factors must be sorted by contribution descending")
        expected_level = (
            RiskLevel.LOW
            if self.score < 25
            else RiskLevel.MODERATE
            if self.score < 50
            else RiskLevel.HIGH
            if self.score < 75
            else RiskLevel.VERY_HIGH
        )
        if self.level is not expected_level:
            raise ValueError("risk level does not match score threshold")
        if self.is_provisional and self.level is RiskLevel.VERY_HIGH:
            raise ValueError("provisional results cannot be very_high in v1")
        return self


__all__ = [
    "BaselineStatus",
    "BurnoutRiskEvaluationRequest",
    "BurnoutRiskEvaluationResponse",
    "CurrentRiskSignals",
    "DataQuality",
    "EmotionProbabilities",
    "FactorCategory",
    "FactorCode",
    "FactorKind",
    "PersonalBaseline",
    "RiskCategory",
    "RiskFactor",
    "RiskLevel",
    "RiskSummary",
]
