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

PROMPT_VERSION: Literal["recovery-report-prompt-v1"] = (
    "recovery-report-prompt-v1"
)

NonEmptyText = Annotated[str, Field(min_length=1)]

def _reject_non_json_number(value: object) -> object:
    if isinstance(value, (bool, str, bytes, bytearray)):
        raise ValueError("numeric fields require JSON number values")  # noqa: TRY004
    return value


JsonNumber = Annotated[float, BeforeValidator(_reject_non_json_number)]
JsonInteger = Annotated[int, BeforeValidator(_reject_non_json_number)]
OptionalNumber = JsonNumber | None


class _RecoveryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
        from_attributes=True,
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
    BREATHING_5 = "BREATHING_5"
    TALK_TO_SOMEONE = "TALK_TO_SOMEONE"
    SMALL_SUCCESS_TASK = "SMALL_SUCCESS_TASK"
    STEP_AWAY_5 = "STEP_AWAY_5"


class RecoveryDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"


class ReportGenerationStatus(StrEnum):
    LLM_GENERATED = "llm_generated"
    TEMPLATE_FALLBACK = "template_fallback"


class RecoveryReportPeriod(_RecoveryModel):
    start: date
    end: date
    record_days: Annotated[JsonInteger, Field(ge=0, le=7)]

    @model_validator(mode="after")
    def validate_period(self) -> RecoveryReportPeriod:
        if self.start > self.end:
            raise ValueError("period start must be on or before end")
        if (self.end - self.start).days > 6:
            raise ValueError("recovery report period cannot exceed seven days")
        return self


class RecoveryReportChange(_RecoveryModel):
    factor_code: ReportFactorCode
    metric: ReportMetric | None
    recent_value: Annotated[JsonNumber, Field(ge=0)] | None
    baseline_value: Annotated[JsonNumber, Field(ge=0)] | None
    delta: OptionalNumber
    change_percent: OptionalNumber
    sample_days: Annotated[JsonInteger, Field(ge=0, le=7)]
    fact_text: Annotated[str, Field(min_length=1, max_length=240)]

    @model_validator(mode="after")
    def validate_numeric_group(self) -> RecoveryReportChange:
        values = (
            self.recent_value,
            self.baseline_value,
            self.delta,
            self.change_percent,
        )
        if self.metric is None:
            if any(value is not None for value in values) or self.sample_days != 0:
                raise ValueError("non-numeric changes cannot contain metric values")
            return self
        if self.recent_value is None or self.sample_days == 0:
            raise ValueError("numeric changes require a recent value and sample days")
        if self.baseline_value is None:
            if self.delta is not None or self.change_percent is not None:
                raise ValueError("delta values require a baseline value")
        elif self.delta is None:
            raise ValueError("baseline values require a delta")
        return self


class RecoveryAction(_RecoveryModel):
    id: RecoveryActionId
    title: Annotated[str, Field(min_length=1, max_length=100)]
    duration_minutes: Annotated[JsonInteger, Field(ge=1, le=1440)] | None
    difficulty: RecoveryDifficulty


class RecoveryReportGenerationRequest(_RecoveryModel):
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
    prompt_version: Literal["recovery-report-prompt-v1"] = PROMPT_VERSION

    @model_validator(mode="after")
    def validate_unique_identifiers(self) -> RecoveryReportGenerationRequest:
        factor_codes = [item.factor_code for item in self.changes]
        action_ids = [item.id for item in self.selected_actions]
        if len(set(factor_codes)) != len(factor_codes):
            raise ValueError("changes must have unique factor codes")
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("selected actions must have unique ids")
        if len(set(self.stage2_signal_drivers)) != len(self.stage2_signal_drivers):
            raise ValueError("stage2 signal drivers must be unique")
        return self


class RecoveryChangedItem(_RecoveryModel):
    factor_code: ReportFactorCode
    title: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(min_length=1, max_length=320)]


class RecoveryRecommendationDescription(_RecoveryModel):
    action_id: RecoveryActionId
    reason: Annotated[str, Field(min_length=1, max_length=320)]


class RecoveryReportCopy(_RecoveryModel):
    headline: Annotated[str, Field(min_length=1, max_length=120)]
    summary: Annotated[str, Field(min_length=1, max_length=500)]
    weekly_observation: Annotated[str, Field(min_length=1, max_length=500)]
    changed_items: Annotated[list[RecoveryChangedItem], Field(max_length=3)]
    recommendation_intro: Annotated[str, Field(min_length=1, max_length=160)]
    recommendation_descriptions: Annotated[
        list[RecoveryRecommendationDescription],
        Field(min_length=1, max_length=3),
    ]


class RecoveryReportGenerationResponse(RecoveryReportCopy):
    model_name: Annotated[str, Field(min_length=1, max_length=128)]
    prompt_version: Literal["recovery-report-prompt-v1"]

    def validate_against(
        self,
        request: RecoveryReportGenerationRequest,
    ) -> None:
        expected_factors = [item.factor_code for item in request.changes]
        actual_factors = [item.factor_code for item in self.changed_items]
        if actual_factors != expected_factors:
            raise ValueError("generated changed items do not match supplied changes")

        expected_actions = [item.id for item in request.selected_actions]
        actual_actions = [
            item.action_id for item in self.recommendation_descriptions
        ]
        if actual_actions != expected_actions:
            raise ValueError(
                "generated recommendations do not match selected actions"
            )
        if self.prompt_version != request.prompt_version:
            raise ValueError("generated prompt version does not match request")


__all__ = [
    "PROMPT_VERSION",
    "RecoveryAction",
    "RecoveryActionId",
    "RecoveryChangedItem",
    "RecoveryDifficulty",
    "RecoveryRecommendationDescription",
    "RecoveryReportChange",
    "RecoveryReportCopy",
    "RecoveryReportGenerationRequest",
    "RecoveryReportGenerationResponse",
    "RecoveryReportPeriod",
    "ReportFactorCode",
    "ReportGenerationStatus",
    "ReportMetric",
]
