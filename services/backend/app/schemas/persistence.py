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
    LETHARGY = "무기력"


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
    model_version: Annotated[str, Field(min_length=1, max_length=128)]
    predicted_emotion: EmotionLabel
    confidence: Probability
    is_uncertain: bool
    probabilities: dict[EmotionLabel, Probability]
    input_hash: Annotated[str, Field(min_length=1, max_length=128)] | None = None

    @model_validator(mode="after")
    def validate_emotion_result(self) -> EmotionResultCreate:
        if self.analyzed_at.tzinfo is None or self.analyzed_at.utcoffset() is None:
            raise ValueError("analyzed_at must include a timezone")
        if set(self.probabilities) != set(EmotionLabel):
            raise ValueError("probabilities must contain exactly six emotion labels")
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
    "EmotionLabel",
    "EmotionResultCreate",
    "EmotionResultRead",
    "RiskEvaluationRead",
]
