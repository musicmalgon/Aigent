from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.persistence import BehavioralDailyRecord
from app.repositories import PersistenceConflictError
from app.schemas.persistence import DailyRecordPersistenceCreate


def create_daily_record(
    session: Session,
    *,
    user_id: str,
    payload: DailyRecordPersistenceCreate,
) -> BehavioralDailyRecord:
    if get_daily_record_by_date(
        session,
        user_id=user_id,
        record_date=payload.record_date,
    ):
        raise PersistenceConflictError(
            "a daily record already exists for this user and date"
        )
    record = BehavioralDailyRecord(
        user_id=user_id,
        **payload.model_dump(),
    )
    session.add(record)
    session.flush()
    return record


def get_daily_record(
    session: Session,
    *,
    user_id: str,
    record_id: str,
) -> BehavioralDailyRecord | None:
    return session.scalar(
        select(BehavioralDailyRecord).where(
            BehavioralDailyRecord.id == record_id,
            BehavioralDailyRecord.user_id == user_id,
        )
    )


def get_daily_record_by_date(
    session: Session,
    *,
    user_id: str,
    record_date: date,
) -> BehavioralDailyRecord | None:
    return session.scalar(
        select(BehavioralDailyRecord).where(
            BehavioralDailyRecord.user_id == user_id,
            BehavioralDailyRecord.record_date == record_date,
        )
    )


def list_daily_records(
    session: Session,
    *,
    user_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[BehavioralDailyRecord]:
    statement = select(BehavioralDailyRecord).where(
        BehavioralDailyRecord.user_id == user_id
    )
    if start_date is not None:
        statement = statement.where(
            BehavioralDailyRecord.record_date >= start_date
        )
    if end_date is not None:
        statement = statement.where(
            BehavioralDailyRecord.record_date <= end_date
        )
    statement = statement.order_by(
        BehavioralDailyRecord.record_date.desc(),
        BehavioralDailyRecord.created_at.desc(),
    )
    return list(session.scalars(statement))


def update_daily_record(
    session: Session,
    *,
    record: BehavioralDailyRecord,
    payload: DailyRecordPersistenceCreate,
) -> BehavioralDailyRecord:
    for field, value in payload.model_dump(exclude={"record_date"}).items():
        setattr(record, field, value)
    session.add(record)
    session.flush()
    return record


__all__ = [
    "create_daily_record",
    "get_daily_record",
    "get_daily_record_by_date",
    "list_daily_records",
    "update_daily_record",
]