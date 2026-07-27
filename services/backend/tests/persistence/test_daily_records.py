from __future__ import annotations

from datetime import UTC, date, time

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.persistence import BehavioralDailyRecord
from app.models.user import User
from app.repositories import PersistenceConflictError
from app.repositories.behavioral_records import (
    create_daily_record,
    get_daily_record,
    get_daily_record_by_date,
    list_daily_records,
)
from app.schemas.persistence import DailyRecordPersistenceCreate
from tests.daily_record_contract import METRIC_FIELDS


def test_create_lookup_list_and_user_scope(
    db_session: Session,
    user: User,
    other_user: User,
) -> None:
    arbitrary_precision_value = 2**100 + 12345
    record = create_daily_record(
        db_session,
        user_id=user.id,
        payload=DailyRecordPersistenceCreate(
            record_date=date(2026, 7, 20),
            sleep_minutes=420,
            bedtime=time(23, 30),
            wake_time=time(6, 30),
            active_minutes=52,
            study_work_minutes=480,
            steps=arbitrary_precision_value,
            schedule_count=arbitrary_precision_value,
            subjective_fatigue=None,
            source_by_field={field: "manual" for field in METRIC_FIELDS},
            coverage_by_field={
                **{field: "complete" for field in METRIC_FIELDS},
                "subjective_fatigue": "unavailable",
            },
        ),
    )

    assert (
        get_daily_record(
            db_session,
            user_id=user.id,
            record_id=record.id,
        )
        is record
    )
    assert (
        get_daily_record_by_date(
            db_session,
            user_id=user.id,
            record_date=record.record_date,
        )
        is record
    )
    assert list_daily_records(db_session, user_id=user.id) == [record]
    assert (
        get_daily_record(
            db_session,
            user_id=other_user.id,
            record_id=record.id,
        )
        is None
    )
    assert record.subjective_fatigue is None
    assert record.bedtime == time(23, 30)
    assert record.wake_time == time(6, 30)
    assert record.steps == arbitrary_precision_value
    assert record.active_minutes == 52
    assert record.schedule_count == arbitrary_precision_value
    assert record.source.value == "manual"
    assert set(record.source_by_field or {}) == set(METRIC_FIELDS)


def test_duplicate_user_date_is_rejected(
    db_session: Session,
    user: User,
) -> None:
    payload = DailyRecordPersistenceCreate(record_date=date(2026, 7, 20))
    create_daily_record(db_session, user_id=user.id, payload=payload)

    with pytest.raises(PersistenceConflictError):
        create_daily_record(db_session, user_id=user.id, payload=payload)


def test_daily_record_time_round_trip_preserves_naive_whole_seconds(
    db_session: Session,
    user: User,
) -> None:
    user_id = user.id
    record = create_daily_record(
        db_session,
        user_id=user_id,
        payload=DailyRecordPersistenceCreate(
            record_date=date(2026, 7, 20),
            bedtime=time(23, 30, 59),
            wake_time=time(6, 7, 8),
        ),
    )
    record_id = record.id
    db_session.commit()
    db_session.expire_all()

    reloaded = get_daily_record(
        db_session,
        user_id=user_id,
        record_id=record_id,
    )

    assert reloaded is not None
    assert reloaded.bedtime is not None
    assert reloaded.wake_time is not None
    assert reloaded.bedtime == time(23, 30, 59)
    assert reloaded.wake_time == time(6, 7, 8)
    assert reloaded.bedtime.tzinfo is None
    assert reloaded.wake_time.tzinfo is None
    assert reloaded.bedtime.microsecond == 0
    assert reloaded.wake_time.microsecond == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bedtime", time(23, 30, microsecond=1)),
        ("wake_time", time(6, 30, tzinfo=UTC)),
    ],
)
def test_daily_record_rejects_non_whole_second_or_aware_times(
    field: str,
    value: time,
) -> None:
    with pytest.raises(ValidationError):
        DailyRecordPersistenceCreate.model_validate(
            {"record_date": "2026-07-20", field: value}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sleep_minutes", -1),
        ("sleep_minutes", 1441),
        ("steps", -1),
        ("active_minutes", 1441),
        ("study_work_minutes", 1441),
        ("rest_minutes", -1),
        ("exercise_minutes", 1441),
        ("schedule_count", -1),
        ("subjective_stress", 10.1),
        ("subjective_fatigue", -0.1),
        ("data_completeness", 1.1),
        ("timezone", "not/a/real-zone"),
    ],
)
def test_daily_record_rejects_invalid_ranges(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        DailyRecordPersistenceCreate.model_validate(
            {"record_date": "2026-07-20", field: value}
        )


def test_deleting_user_cascades_daily_records(
    db_session: Session,
    user: User,
) -> None:
    record = create_daily_record(
        db_session,
        user_id=user.id,
        payload=DailyRecordPersistenceCreate(record_date=date(2026, 7, 20)),
    )
    record_id = record.id

    db_session.delete(user)
    db_session.flush()

    assert (
        db_session.scalar(
            select(BehavioralDailyRecord).where(BehavioralDailyRecord.id == record_id)
        )
        is None
    )
