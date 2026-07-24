from __future__ import annotations

from datetime import date

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
from app.schemas.persistence import DailyRecordCreate


def test_create_lookup_list_and_user_scope(
    db_session: Session,
    user: User,
    other_user: User,
) -> None:
    record = create_daily_record(
        db_session,
        user_id=user.id,
        payload=DailyRecordCreate(
            record_date=date(2026, 7, 20),
            sleep_minutes=420,
            subjective_stress=4,
            subjective_fatigue=None,
        ),
    )

    assert get_daily_record(
        db_session,
        user_id=user.id,
        record_id=record.id,
    ) is record
    assert get_daily_record_by_date(
        db_session,
        user_id=user.id,
        record_date=record.record_date,
    ) is record
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
    assert record.source.value == "manual"


def test_duplicate_user_date_is_rejected(
    db_session: Session,
    user: User,
) -> None:
    payload = DailyRecordCreate(record_date=date(2026, 7, 20))
    create_daily_record(db_session, user_id=user.id, payload=payload)

    with pytest.raises(PersistenceConflictError):
        create_daily_record(db_session, user_id=user.id, payload=payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sleep_minutes", -1),
        ("sleep_minutes", 1441),
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
        DailyRecordCreate.model_validate(
            {"record_date": "2026-07-20", field: value}
        )


def test_deleting_user_cascades_daily_records(
    db_session: Session,
    user: User,
) -> None:
    record = create_daily_record(
        db_session,
        user_id=user.id,
        payload=DailyRecordCreate(record_date=date(2026, 7, 20)),
    )
    record_id = record.id

    db_session.delete(user)
    db_session.flush()

    assert db_session.scalar(
        select(BehavioralDailyRecord).where(
            BehavioralDailyRecord.id == record_id
        )
    ) is None
