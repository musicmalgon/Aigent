from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.persistence import BehavioralDailyRecord
from app.models.user import User
from app.repositories import PersistenceConflictError
from app.repositories.behavioral_records import (
    create_daily_record,
    delete_daily_record,
    get_daily_record_by_date,
    list_daily_records,
    update_daily_record,
)
from app.schemas.behavioral_records import DailyRecordCreate, DailyRecordRead
from app.services.behavioral_record_mapper import (
    DailyRecordMetadataUnavailableError,
    to_daily_record_read,
    to_persistence_create,
)

DEFAULT_RANGE_DAYS = 14
MAX_RANGE_DAYS = 28
DAILY_RECORD_UNIQUE_CONSTRAINT = "uq_behavioral_daily_records_user_date"
DAILY_RECORD_METADATA_UNAVAILABLE_DETAIL = (
    "Behavioral record field metadata is unavailable."
)

router = APIRouter(
    prefix="/api/v1/behavioral-records",
    tags=["behavioral-records"],
)


def _today_in_timezone(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _is_daily_record_unique_violation(exc: IntegrityError) -> bool:
    diagnostic = getattr(exc.orig, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if constraint_name == DAILY_RECORD_UNIQUE_CONSTRAINT:
        return True

    message = str(exc.orig).lower()
    if DAILY_RECORD_UNIQUE_CONSTRAINT in message:
        return True
    return (
        "unique constraint failed" in message
        and "behavioral_daily_records.user_id" in message
        and "behavioral_daily_records.record_date" in message
    )


def _duplicate_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="A behavioral record already exists for this date.",
    )


def _serialize_daily_record(
    record: BehavioralDailyRecord,
) -> DailyRecordRead:
    try:
        return to_daily_record_read(record)
    except DailyRecordMetadataUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DAILY_RECORD_METADATA_UNAVAILABLE_DETAIL,
        ) from exc


def _resolve_date_range(
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    if (date_from is None) != (date_to is None):
        raise HTTPException(
            status_code=422,
            detail="date_from and date_to must be provided together.",
        )

    resolved_to = date_to or _utc_today()
    resolved_from = date_from or (resolved_to - timedelta(days=DEFAULT_RANGE_DAYS - 1))

    if resolved_from > resolved_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be on or before date_to.",
        )
    if (resolved_to - resolved_from).days >= MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Date range cannot exceed {MAX_RANGE_DAYS} inclusive days.",
        )
    return resolved_from, resolved_to


@router.post(
    "",
    response_model=DailyRecordRead,
    status_code=status.HTTP_201_CREATED,
)
def create_behavioral_record(
    payload: DailyRecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DailyRecordRead:
    if payload.date > _today_in_timezone(payload.time_zone):
        raise HTTPException(
            status_code=422,
            detail="date cannot be in the future for the submitted time_zone.",
        )

    try:
        record = create_daily_record(
            db,
            user_id=current_user.id,
            payload=to_persistence_create(payload),
        )
        db.commit()
    except PersistenceConflictError as exc:
        db.rollback()
        raise _duplicate_error() from exc
    except IntegrityError as exc:
        db.rollback()
        if _is_daily_record_unique_violation(exc):
            raise _duplicate_error() from exc
        raise
    except SQLAlchemyError:
        db.rollback()
        raise

    db.refresh(record)
    return _serialize_daily_record(record)


@router.get("", response_model=list[DailyRecordRead])
def read_behavioral_records(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DailyRecordRead]:
    resolved_from, resolved_to = _resolve_date_range(date_from, date_to)
    return [
        _serialize_daily_record(record)
        for record in list_daily_records(
            db,
            user_id=current_user.id,
            start_date=resolved_from,
            end_date=resolved_to,
        )
    ]


@router.get("/{record_date}", response_model=DailyRecordRead)
def read_behavioral_record(
    record_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DailyRecordRead:
    record = get_daily_record_by_date(
        db,
        user_id=current_user.id,
        record_date=record_date,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Behavioral record not found.",
        )
    return _serialize_daily_record(record)


@router.put("/{record_date}", response_model=DailyRecordRead)
def update_behavioral_record(
    record_date: date,
    payload: DailyRecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DailyRecordRead:
    if payload.date != record_date:
        raise HTTPException(
            status_code=422,
            detail="date in the request body must match the URL date.",
        )
    if payload.date > _today_in_timezone(payload.time_zone):
        raise HTTPException(
            status_code=422,
            detail="date cannot be in the future for the submitted time_zone.",
        )

    record = get_daily_record_by_date(
        db,
        user_id=current_user.id,
        record_date=record_date,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Behavioral record not found.",
        )

    try:
        record = update_daily_record(
            db,
            record=record,
            payload=to_persistence_create(payload),
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    db.refresh(record)
    return _serialize_daily_record(record)

@router.delete(
    "/{record_date}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_behavioral_record(
    record_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    record = get_daily_record_by_date(
        db,
        user_id=current_user.id,
        record_date=record_date,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Behavioral record not found.",
        )

    try:
        delete_daily_record(db, record=record)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

__all__ = ["router"]