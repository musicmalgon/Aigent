from __future__ import annotations

from datetime import date
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

PROMPT_VERSION = "recovery-report-prompt-v1"


def _reject_non_json_number(value: object) -> object:
    if isinstance(value, (bool, str, bytes, bytearray)):
        raise ValueError("numeric fields require JSON number values")  # noqa: TRY004
    return value


JsonNumber = Annotated[float, BeforeValidator(_reject_non_json_number)]
JsonInteger = Annotated[int, BeforeValidator(_reject_non_json_number)]


class _ReportModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class ReportFactorCode(StrEnum):
    SLEEP_DECREASE = "sleep_decrease"
    WORKLOAD_INCREASE = "workload_increase"
    SCHEDULE_OVERLOAD = "schedule_overload"
    REST_DECREASE = "rest_decrease"
    EXERCISE_DECREASE = "exercise_decrease"
    NEGATIVE_EMOTION_INCREASE = "negative_emotion_increase"
    HIGH_NEGATIVE_EMOTION = "high_negative_emotion"
    SUBJECTIVE_STRESS = "subjective_stress"
    SUBJECTIVE_FATIGUE = "subjective_fatigue"


class ReportMetric(StrEnum):
    SLEEP_MINUTES = "sleep_minutes"
    WORK_OR_STUDY_MINUTES = "work_or_study_minutes"
    REST_MINUTES = "rest_minutes"
    EXERCISE_MINUTES = "exercise_minutes"
    SCHEDULE_COUNT = "schedule_count"
    NEGATIVE_EMOTION_PROBABILITY = "negative_emotion_probability"
    SUBJECTIVE_STRESS = "subjective_stress"
    SUBJECTIVE_FATIGUE = "subjective_fatigue"


class RecoveryActionId(StrEnum):
    REST_30 = "REST_30"
    SLEEP_EARLY_60 = "SLEEP_EARLY_60"
    LIGHT_ACTIVITY_20 = "LIGHT_ACTIVITY_20"
    SCHEDULE_REDUCE_ONE = "SCHEDULE_REDUCE_ONE"
    JOURNAL_CHECKIN_10 = "JOURNAL_CHECKIN_10"
    ROUTINE_CHECK_5 = "ROUTINE_CHECK_5"


class RecoveryReportPeriod(_ReportModel):
    start: date
    end: date
    record_days: Annotated[JsonInteger, Field(ge=0, le=7)]

    @model_validator(mode="after")
    def validate_dates(self) -> RecoveryReportPeriod:
        if self.start > self.end or (self.end - self.start).days > 6:
            raise ValueError("report period must be a valid seven-day window")
        return self


class RecoveryReportChange(_ReportModel):
    factor_code: ReportFactorCode
    metric: ReportMetric | None
    recent_value: Annotated[JsonNumber, Field(ge=0)] | None
    baseline_value: Annotated[JsonNumber, Field(ge=0)] | None
    delta: JsonNumber | None
    change_percent: JsonNumber | None
    sample_days: Annotated[JsonInteger, Field(ge=0, le=7)]
    fact_text: Annotated[str, Field(min_length=1, max_length=240)]


class RecoveryAction(_ReportModel):
    id: RecoveryActionId
    title: Annotated[str, Field(min_length=1, max_length=100)]
    duration_minutes: Annotated[JsonInteger, Field(ge=1, le=1440)] | None
    difficulty: Literal["easy", "medium"]


class RecoveryReportGenerationRequest(_ReportModel):
    risk_level: Literal["low", "moderate", "high", "very_high"]
    risk_score: Annotated[JsonNumber, Field(ge=0, le=100)]
    is_provisional: StrictBool
    data_quality: Literal["sufficient", "insufficient"]
    period: RecoveryReportPeriod
    changes: Annotated[list[RecoveryReportChange], Field(max_length=3)]
    selected_actions: Annotated[
        list[RecoveryAction],
        Field(min_length=1, max_length=3),
    ]
    stage2_signal_drivers: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=32)]],
        Field(max_length=6),
    ] = Field(default_factory=list)
    prompt_version: Literal["recovery-report-prompt-v1"]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> RecoveryReportGenerationRequest:
        factors = [item.factor_code for item in self.changes]
        actions = [item.id for item in self.selected_actions]
        if len(set(factors)) != len(factors):
            raise ValueError("changes must have unique factor codes")
        if len(set(actions)) != len(actions):
            raise ValueError("selected actions must have unique ids")
        if len(set(self.stage2_signal_drivers)) != len(self.stage2_signal_drivers):
            raise ValueError("stage2 signal drivers must be unique")
        return self


class RecoveryActionCandidate(_ReportModel):
    id: Annotated[str, Field(min_length=1, max_length=64)]
    label: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(min_length=1, max_length=320)]
    signals: list[Annotated[str, Field(min_length=1, max_length=32)]]


class RecoveryActionSelectionRequest(_ReportModel):
    candidates: Annotated[list[RecoveryActionCandidate], Field(min_length=1)]
    stage2_signals: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(default_factory=list)
    factor_codes: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list)
    risk_level: Annotated[str, Field(min_length=1, max_length=32)]
    risk_score: Annotated[JsonNumber, Field(ge=0, le=100)]
    data_quality: Annotated[str, Field(min_length=1, max_length=32)]
    is_provisional: StrictBool


class RecoveryActionSelectionResponse(_ReportModel):
    ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=64)]], Field(min_length=1, max_length=3)]


class RecoveryChangedItem(_ReportModel):
    factor_code: ReportFactorCode
    title: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(min_length=1, max_length=320)]


class RecoveryRecommendationDescription(_ReportModel):
    action_id: RecoveryActionId
    reason: Annotated[str, Field(min_length=1, max_length=320)]


class RecoveryReportCopy(_ReportModel):
    headline: Annotated[str, Field(min_length=1, max_length=120)]
    summary: Annotated[str, Field(min_length=1, max_length=500)]
    weekly_observation: Annotated[str, Field(min_length=1, max_length=500)]
    changed_items: Annotated[list[RecoveryChangedItem], Field(max_length=3)]
    recommendation_intro: Annotated[str, Field(min_length=1, max_length=160)]
    recommendation_descriptions: Annotated[
        list[RecoveryRecommendationDescription],
        Field(min_length=1, max_length=3),
    ]

    def validate_against(
        self,
        request: RecoveryReportGenerationRequest,
    ) -> None:
        if [item.factor_code for item in self.changed_items] != [
            item.factor_code for item in request.changes
        ]:
            raise ValueError("changed items do not match supplied changes")
        if [
            item.action_id for item in self.recommendation_descriptions
        ] != [item.id for item in request.selected_actions]:
            raise ValueError("recommendations do not match selected actions")


class RecoveryReportGenerationResponse(RecoveryReportCopy):
    model_name: Annotated[str, Field(min_length=1, max_length=128)]
    prompt_version: Literal["recovery-report-prompt-v1"]


__all__ = [
    "PROMPT_VERSION",
    "RecoveryAction",
    "RecoveryActionCandidate",
    "RecoveryActionId",
    "RecoveryActionSelectionRequest",
    "RecoveryActionSelectionResponse",
    "RecoveryChangedItem",
    "RecoveryRecommendationDescription",
    "RecoveryReportChange",
    "RecoveryReportCopy",
    "RecoveryReportGenerationRequest",
    "RecoveryReportGenerationResponse",
    "RecoveryReportPeriod",
    "ReportFactorCode",
    "ReportMetric",
]
