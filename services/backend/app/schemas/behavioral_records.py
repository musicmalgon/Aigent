from __future__ import annotations

import re
from datetime import date, datetime, time
from enum import StrEnum
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictFloat,
    WithJsonSchema,
    field_validator,
    model_validator,
)

DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
TIME_PATTERN = r"^[0-9]{2}:[0-9]{2}:[0-9]{2}$"
TIME_ZONE_PATTERN = (
    r"^[A-Za-z][A-Za-z0-9._+-]*"
    r"(?:/[A-Za-z0-9][A-Za-z0-9._+-]*)*$"
)


def _reject_non_json_number(value: object) -> object:
    if isinstance(value, (bool, str, bytes, bytearray)):
        raise ValueError("numeric fields require JSON number values")
    return value


def _validate_date_input(value: object) -> object:
    if isinstance(value, datetime):
        raise ValueError("date must be a YYYY-MM-DD string or date object")
    if not isinstance(value, (str, date)):
        raise ValueError("date must be a YYYY-MM-DD string or date object")
    if isinstance(value, str) and re.fullmatch(DATE_PATTERN, value) is None:
        raise ValueError("date strings must use YYYY-MM-DD")
    return value


def _validate_local_time_input(value: object) -> object:
    if not isinstance(value, (str, time)):
        raise ValueError(
            "bedtime and wake_time must be HH:MM:SS strings or time objects"
        )
    if isinstance(value, str) and re.fullmatch(TIME_PATTERN, value) is None:
        raise ValueError("bedtime and wake_time strings must use HH:MM:SS")
    return value


def _validate_local_time(value: time) -> time:
    if value.tzinfo is not None or value.microsecond != 0:
        raise ValueError(
            "bedtime and wake_time must be whole-second local times "
            "without a UTC offset"
        )
    return value


JSONInteger = Annotated[int, BeforeValidator(_reject_non_json_number)]
DayMinutes = Annotated[JSONInteger, Field(ge=0, le=1440)]
NonNegativeInteger = Annotated[JSONInteger, Field(ge=0)]
NonNegativeNumber = Annotated[StrictFloat, Field(ge=0)]
LocalDate = Annotated[
    date,
    BeforeValidator(_validate_date_input),
    WithJsonSchema({"type": "string", "format": "date"}),
]
LocalTime = Annotated[
    time,
    BeforeValidator(_validate_local_time_input),
    AfterValidator(_validate_local_time),
    WithJsonSchema(
        {
            "type": "string",
            "format": "time",
            "pattern": TIME_PATTERN,
        }
    ),
]
TimeZoneName = Annotated[
    str,
    Field(
        min_length=1,
        pattern=TIME_ZONE_PATTERN,
        json_schema_extra={"not": {"pattern": r"\s"}},
    ),
]
NonBlankString = Annotated[str, Field(min_length=1, pattern=r"\S")]


class ContractSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )


class DataSource(StrEnum):
    HEALTH_PLATFORM = "health_platform"
    MANUAL = "manual"
    SYNTHETIC = "synthetic"
    NOT_PROVIDED = "not_provided"


class DataCoverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class SourceByField(ContractSchema):
    sleep_minutes: DataSource
    bedtime: DataSource
    wake_time: DataSource
    steps: DataSource
    active_minutes: DataSource
    exercise_minutes: DataSource
    work_or_study_minutes: DataSource
    rest_minutes: DataSource
    schedule_count: DataSource
    subjective_fatigue: DataSource


class CoverageByField(ContractSchema):
    sleep_minutes: DataCoverage
    bedtime: DataCoverage
    wake_time: DataCoverage
    steps: DataCoverage
    active_minutes: DataCoverage
    exercise_minutes: DataCoverage
    work_or_study_minutes: DataCoverage
    rest_minutes: DataCoverage
    schedule_count: DataCoverage
    subjective_fatigue: DataCoverage


BEHAVIORAL_FIELD_NAMES = (
    "sleep_minutes",
    "bedtime",
    "wake_time",
    "steps",
    "active_minutes",
    "exercise_minutes",
    "work_or_study_minutes",
    "rest_minutes",
    "schedule_count",
    "subjective_fatigue",
)


def _conditional_metadata_schema(field_name: str) -> dict[str, Any]:
    return {
        "oneOf": [
            {
                "properties": {
                    field_name: {"type": "null"},
                    "coverage_by_field": {
                        "properties": {
                            field_name: {"const": "unavailable"},
                        }
                    },
                }
            },
            {
                "properties": {
                    field_name: {
                        "not": {
                            "type": "null",
                        }
                    },
                    "source_by_field": {
                        "properties": {
                            field_name: {
                                "not": {
                                    "const": "not_provided",
                                }
                            }
                        }
                    },
                    "coverage_by_field": {
                        "properties": {
                            field_name: {
                                "enum": [
                                    "complete",
                                    "partial",
                                ]
                            }
                        }
                    },
                }
            },
        ]
    }


DAILY_RECORD_CONDITIONAL_ALLOF: list[Any] = [
    _conditional_metadata_schema(field_name)
    for field_name in BEHAVIORAL_FIELD_NAMES
]


class DailyRecordCreate(ContractSchema):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": DAILY_RECORD_CONDITIONAL_ALLOF,
        }
    )

    date: LocalDate
    time_zone: TimeZoneName
    sleep_minutes: DayMinutes | None
    bedtime: LocalTime | None
    wake_time: LocalTime | None
    steps: NonNegativeInteger | None
    active_minutes: DayMinutes | None
    exercise_minutes: DayMinutes | None
    work_or_study_minutes: DayMinutes | None
    rest_minutes: DayMinutes | None
    schedule_count: NonNegativeInteger | None
    subjective_fatigue: NonNegativeNumber | None
    source_by_field: SourceByField
    coverage_by_field: CoverageByField

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("time_zone must be a valid IANA zone") from exc
        return value

    @model_validator(mode="after")
    def validate_field_metadata(self) -> DailyRecordCreate:
        for field_name in BEHAVIORAL_FIELD_NAMES:
            value = getattr(self, field_name)
            source = getattr(self.source_by_field, field_name)
            coverage = getattr(self.coverage_by_field, field_name)

            if value is None and coverage is not DataCoverage.UNAVAILABLE:
                raise ValueError(
                    f"{field_name} requires unavailable coverage when it is null"
                )
            if value is not None and coverage is DataCoverage.UNAVAILABLE:
                raise ValueError(
                    f"{field_name} must be null when coverage is unavailable"
                )
            if value is not None and source is DataSource.NOT_PROVIDED:
                raise ValueError(
                    f"{field_name} must be null when its source is not_provided"
                )
        return self


class DailyRecordRead(DailyRecordCreate):
    user_id: NonBlankString


__all__ = [
    "CoverageByField",
    "DailyRecordCreate",
    "DailyRecordRead",
    "DataCoverage",
    "DataSource",
    "SourceByField",
]
