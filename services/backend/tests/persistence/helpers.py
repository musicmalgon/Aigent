from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.persistence import (
    BehavioralDailyRecord,
    EmotionAnalysisResult,
)
from app.repositories.behavioral_records import create_daily_record
from app.repositories.emotion_results import create_emotion_result
from app.schemas.persistence import (
    DailyRecordCreate,
    EmotionLabel,
    EmotionResultCreate,
)


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
    study_work_minutes: int | None = 480,
    rest_minutes: int | None = 60,
    exercise_minutes: int | None = 20,
    schedule_count: int | None = 4,
    subjective_stress: float | None = 5,
    subjective_fatigue: float | None = 5,
) -> BehavioralDailyRecord:
    return create_daily_record(
        session,
        user_id=user_id,
        payload=DailyRecordCreate(
            record_date=record_date,
            sleep_minutes=sleep_minutes,
            study_work_minutes=study_work_minutes,
            rest_minutes=rest_minutes,
            exercise_minutes=exercise_minutes,
            schedule_count=schedule_count,
            subjective_stress=subjective_stress,
            subjective_fatigue=subjective_fatigue,
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
