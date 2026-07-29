from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy.orm import Session

from app.models.persistence import (
    BehavioralDailyRecord,
    EmotionAnalysisResult,
)
from app.repositories.behavioral_records import create_daily_record
from app.repositories.emotion_results import create_emotion_result
from app.schemas.persistence import (
    DailyRecordPersistenceCreate,
    EmotionLabel,
    EmotionResultCreate,
)
from tests.daily_record_contract import METRIC_FIELDS


def probabilities(
    *,
    joy: float = 0.2,
) -> dict[EmotionLabel, float]:
    remaining = round((1.0 - joy) / 5.0, 10)
    values = {
        EmotionLabel.JOY: joy,
        EmotionLabel.ANXIETY: remaining,
        EmotionLabel.EMBARRASSMENT: remaining,
        EmotionLabel.ANGER: remaining,
        EmotionLabel.SADNESS: remaining,
        EmotionLabel.HURT: remaining,
    }
    difference = 1.0 - sum(values.values())
    values[EmotionLabel.HURT] += difference
    return values


def daily_record(
    session: Session,
    *,
    user_id: str,
    record_date: date,
    sleep_minutes: int | None = 420,
    bedtime: time | None = time(23, 30),
    wake_time: time | None = time(6, 30),
    steps: int | None = 7420,
    active_minutes: int | None = 52,
    study_work_minutes: int | None = 480,
    rest_minutes: int | None = 60,
    exercise_minutes: int | None = 20,
    schedule_count: int | None = 4,
    subjective_stress: float | None = 5,
    subjective_fatigue: float | None = 5,
    timezone: str = "UTC",
) -> BehavioralDailyRecord:
    contract_values = {
        "sleep_minutes": sleep_minutes,
        "bedtime": bedtime,
        "wake_time": wake_time,
        "steps": steps,
        "active_minutes": active_minutes,
        "exercise_minutes": exercise_minutes,
        "work_or_study_minutes": study_work_minutes,
        "rest_minutes": rest_minutes,
        "schedule_count": schedule_count,
        "subjective_fatigue": subjective_fatigue,
    }
    return create_daily_record(
        session,
        user_id=user_id,
        payload=DailyRecordPersistenceCreate(
            record_date=record_date,
            timezone=timezone,
            sleep_minutes=sleep_minutes,
            bedtime=bedtime,
            wake_time=wake_time,
            steps=steps,
            active_minutes=active_minutes,
            study_work_minutes=study_work_minutes,
            rest_minutes=rest_minutes,
            exercise_minutes=exercise_minutes,
            schedule_count=schedule_count,
            subjective_stress=subjective_stress,
            subjective_fatigue=subjective_fatigue,
            source_by_field={
                field: (
                    "manual"
                    if contract_values[field] is not None
                    else "not_provided"
                )
                for field in METRIC_FIELDS
            },
            coverage_by_field={
                field: (
                    "complete"
                    if contract_values[field] is not None
                    else "unavailable"
                )
                for field in METRIC_FIELDS
            },
        ),
    )


def emotion_result(
    session: Session,
    *,
    user_id: str,
    record_date: date,
    joy: float = 0.2,
    analyzed_at: datetime | None = None,
) -> EmotionAnalysisResult:
    return create_emotion_result(
        session,
        user_id=user_id,
        payload=EmotionResultCreate(
            record_date=record_date,
            analyzed_at=analyzed_at or datetime.now(UTC),
            model_version="coarse-emotion-test-v1",
            predicted_emotion=EmotionLabel.ANXIETY,
            confidence=0.8,
            is_uncertain=False,
            probabilities=probabilities(joy=joy),
            input_hash="irreversible-test-hash",
        ),
    )


__all__ = ["daily_record", "emotion_result", "probabilities"]
