from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "schemas"
    / "behavioral_daily_record.schema.json"
)
DAILY_RECORD_SCHEMA: dict[str, Any] = json.loads(
    CONTRACT_PATH.read_text(encoding="utf-8")
)
DAILY_RECORD_VALIDATOR = Draft202012Validator(
    DAILY_RECORD_SCHEMA,
    format_checker=FormatChecker(),
)

METRIC_FIELDS = (
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


def canonical_daily_record_payload(
    *,
    record_date: str = "2026-07-20",
    **overrides: object,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "date": record_date,
        "time_zone": "Asia/Seoul",
        "sleep_minutes": 420,
        "bedtime": "23:30:00",
        "wake_time": "06:30:00",
        "steps": 7420,
        "active_minutes": 52,
        "exercise_minutes": 30,
        "work_or_study_minutes": 480,
        "rest_minutes": 60,
        "schedule_count": 5,
        "subjective_fatigue": 6.0,
        "source_by_field": {field: "manual" for field in METRIC_FIELDS},
        "coverage_by_field": {field: "complete" for field in METRIC_FIELDS},
    }
    payload.update(overrides)
    return copy.deepcopy(payload)


def validate_daily_record_response(payload: object) -> None:
    DAILY_RECORD_VALIDATOR.validate(payload)


__all__ = [
    "CONTRACT_PATH",
    "DAILY_RECORD_SCHEMA",
    "DAILY_RECORD_VALIDATOR",
    "METRIC_FIELDS",
    "canonical_daily_record_payload",
    "validate_daily_record_response",
]
