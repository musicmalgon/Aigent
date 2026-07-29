from __future__ import annotations

from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.models.persistence import (
    DailyRecordSource,
    PersistenceBaselineStatus,
)

DayMinutes = Annotated[int, Field(ge=0, le=1440)]
NonNegativeInteger = Annotated[int, Field(ge=0)]
SubjectiveRating = Annotated[float, Field(ge=0, le=10)]
NonNegativeNumber = Annotated[float, Field(ge=0)]
Probability = Annotated[float, Field(ge=0, le=1)]


class EmotionLabel(StrEnum):
    JOY = "기쁨"
    ANXIETY = "불안"
    EMBARRASSMENT = "당황"
    ANGER = "분노"
    SADNESS = "슬픔"
    HURT = "상처"


class EmotionV2Label(StrEnum):
    ANGER = "분노"
    JOY = "기쁨"
    ANXIETY = "불안"
    EMBARRASSMENT = "당황"
    SADNESS = "슬픔"
    LETHARGY = "무기력"


class EmotionTaxonomyVersion(StrEnum):
    V1 = "v1"
    V2 = "v2"


EmotionAnyLabel = EmotionLabel | EmotionV2Label


class PersistenceSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        from_attributes=True,
    )


class DailyRecordPersistenceCreate(PersistenceSchema):
    record_date: date
    sleep_minutes: DayMinutes | None = None
    bedtime: time | None = None
    wake_time: time | None = None
    steps: NonNegativeInteger | None = None
    active_minutes: DayMinutes | None = None
    study_work_minutes: DayMinutes | None = None
    rest_minutes: DayMinutes | None = None
    exercise_minutes: DayMinutes | None = None
    schedule_count: NonNegativeInteger | None = None
    subjective_stress: SubjectiveRating | None = None
    subjective_fatigue: NonNegativeNumber | None = None
    source: DailyRecordSource = DailyRecordSource.MANUAL
    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "UTC"
    data_completeness: Probability | None = None
    source_by_field: dict[str, str] | None = None
    coverage_by_field: dict[str, str] | None = None

    @field_validator("bedtime", "wake_time")
    @classmethod
    def validate_local_time(cls, value: time | None) -> time | None:
        if value is not None and (
            value.tzinfo is not None or value.microsecond != 0
        ):
            raise ValueError(
                "bedtime and wake_time must be whole-second local times "
                "without a UTC offset"
            )
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA zone") from exc
        return value


class EmotionResultCreate(PersistenceSchema):
    record_date: date | None = None
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    taxonomy_version: EmotionTaxonomyVersion = EmotionTaxonomyVersion.V1
    model_version: Annotated[str, Field(min_length=1, max_length=128)]
    predicted_emotion: EmotionAnyLabel
    emotion: EmotionAnyLabel | None = None
    confidence: Probability
    is_uncertain: bool
    probabilities: dict[EmotionAnyLabel, Probability]
    margin: Probability | None = None
    provisional: bool = False
    threshold_version: Annotated[str, Field(min_length=1, max_length=64)] | None = (
        None
    )
    input_hash: Annotated[str, Field(min_length=1, max_length=128)] | None = None

    @model_validator(mode="before")
    @classmethod
    def preserve_v1_defaults(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        taxonomy = normalized.get(
            "taxonomy_version",
            EmotionTaxonomyVersion.V1,
        )
        label_type = (
            EmotionV2Label
            if taxonomy in {EmotionTaxonomyVersion.V2, "v2"}
            else EmotionLabel
        )
        if "predicted_emotion" in normalized:
            normalized["predicted_emotion"] = label_type(
                normalized["predicted_emotion"]
            )
        if normalized.get("emotion") is not None:
            normalized["emotion"] = label_type(normalized["emotion"])
        if isinstance(normalized.get("probabilities"), dict):
            normalized["probabilities"] = {
                label_type(label): probability
                for label, probability in normalized["probabilities"].items()
            }
        if (
            taxonomy in {EmotionTaxonomyVersion.V1, "v1"}
            and "emotion" not in normalized
            and "predicted_emotion" in normalized
        ):
            normalized["emotion"] = normalized["predicted_emotion"]
        return normalized

    @model_validator(mode="after")
    def validate_emotion_result(self) -> EmotionResultCreate:
        if self.analyzed_at.tzinfo is None or self.analyzed_at.utcoffset() is None:
            raise ValueError("analyzed_at must include a timezone")
        expected_labels: set[EmotionAnyLabel]
        if self.taxonomy_version is EmotionTaxonomyVersion.V1:
            expected_labels = set(EmotionLabel)
            if not isinstance(self.predicted_emotion, EmotionLabel):
                raise ValueError("v1 predicted_emotion must use a v1 label")
            if self.emotion is not self.predicted_emotion:
                raise ValueError("v1 emotion must match predicted_emotion")
            if self.margin is not None or self.threshold_version is not None:
                raise ValueError("v1 rows cannot contain v2 threshold provenance")
            if self.provisional:
                raise ValueError("v1 rows cannot use v2 abstention")
        else:
            expected_labels = set(EmotionV2Label)
            if not isinstance(self.predicted_emotion, EmotionV2Label):
                raise ValueError("v2 predicted_emotion must use a v2 label")
            if self.margin is None or self.threshold_version is None:
                raise ValueError("v2 rows require margin and threshold_version")
            if self.provisional != self.is_uncertain:
                raise ValueError("v2 provisional must match is_uncertain")
            expected_emotion = None if self.provisional else self.predicted_emotion
            if self.emotion is not expected_emotion:
                raise ValueError(
                    "v2 emotion must be null exactly when provisional"
                )

        if set(self.probabilities) != expected_labels:
            raise ValueError(
                "probabilities must match the selected taxonomy labels"
            )
        if abs(sum(self.probabilities.values()) - 1.0) > 1e-6:
            raise ValueError("emotion probabilities must sum to 1 within 0.000001")
        return self


class EmotionResultRead(EmotionResultCreate):
    id: str
    user_id: str
    created_at: datetime


class BaselineRead(PersistenceSchema):
    id: str
    user_id: str
    window_start: date
    window_end: date
    sample_days: NonNegativeInteger
    sleep_minutes: float | None
    study_work_minutes: float | None
    rest_minutes: float | None
    exercise_minutes: float | None
    schedule_count: float | None
    subjective_stress: float | None
    subjective_fatigue: float | None
    negative_emotion_probability: float | None
    status: PersistenceBaselineStatus
    algorithm_version: str
    created_at: datetime


class RiskEvaluationRead(PersistenceSchema):
    id: str
    user_id: str
    record_date: date | None
    evaluated_at: datetime
    daily_record_id: str | None
    emotion_analysis_result_id: str | None
    baseline_id: str | None
    engine_version: str
    score: float
    level: str
    is_provisional: bool
    baseline_status: str
    data_quality: str
    category_scores: dict[str, float]
    factors: list[dict[str, Any]]
    summary: dict[str, Any]
    created_at: datetime


__all__ = [
    "BaselineRead",
    "DailyRecordPersistenceCreate",
    "EmotionAnyLabel",
    "EmotionLabel",
    "EmotionResultCreate",
    "EmotionResultRead",
    "EmotionTaxonomyVersion",
    "EmotionV2Label",
    "RiskEvaluationRead",
]
