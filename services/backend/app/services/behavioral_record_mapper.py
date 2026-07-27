from __future__ import annotations

from app.models.persistence import BehavioralDailyRecord
from app.schemas.behavioral_records import DailyRecordCreate, DailyRecordRead
from app.schemas.persistence import DailyRecordPersistenceCreate


class DailyRecordMetadataUnavailableError(RuntimeError):
    """Raised when a persisted row lacks required field-level metadata."""


def to_persistence_create(
    payload: DailyRecordCreate,
) -> DailyRecordPersistenceCreate:
    return DailyRecordPersistenceCreate(
        record_date=payload.date,
        timezone=payload.time_zone,
        sleep_minutes=payload.sleep_minutes,
        bedtime=payload.bedtime,
        wake_time=payload.wake_time,
        steps=payload.steps,
        active_minutes=payload.active_minutes,
        exercise_minutes=payload.exercise_minutes,
        study_work_minutes=payload.work_or_study_minutes,
        rest_minutes=payload.rest_minutes,
        schedule_count=payload.schedule_count,
        subjective_fatigue=payload.subjective_fatigue,
        source_by_field=payload.source_by_field.model_dump(mode="json"),
        coverage_by_field=payload.coverage_by_field.model_dump(mode="json"),
    )


def to_daily_record_read(
    record: BehavioralDailyRecord,
) -> DailyRecordRead:
    if record.source_by_field is None or record.coverage_by_field is None:
        raise DailyRecordMetadataUnavailableError(
            "daily record field metadata is unavailable"
        )
    return DailyRecordRead.model_validate(
        {
            "user_id": record.user_id,
            "date": record.record_date,
            "time_zone": record.timezone,
            "sleep_minutes": record.sleep_minutes,
            "bedtime": record.bedtime,
            "wake_time": record.wake_time,
            "steps": record.steps,
            "active_minutes": record.active_minutes,
            "exercise_minutes": record.exercise_minutes,
            "work_or_study_minutes": record.study_work_minutes,
            "rest_minutes": record.rest_minutes,
            "schedule_count": record.schedule_count,
            "subjective_fatigue": record.subjective_fatigue,
            "source_by_field": record.source_by_field,
            "coverage_by_field": record.coverage_by_field,
        }
    )


__all__ = [
    "DailyRecordMetadataUnavailableError",
    "to_daily_record_read",
    "to_persistence_create",
]
