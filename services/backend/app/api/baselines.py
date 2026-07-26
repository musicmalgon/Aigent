from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.persistence import PersistenceBaselineStatus
from app.models.user import User
from app.repositories.baselines import (
    get_latest_ready_baseline,
    list_baselines,
)
from app.schemas.baseline import BaselineCreate
from app.schemas.persistence import BaselineRead
from app.services.baselines import calculate_and_store_baseline

LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/baselines",
    tags=["baselines"],
)


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _database_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Baseline operation failed.",
    )


@router.post(
    "",
    response_model=BaselineRead,
    status_code=status.HTTP_201_CREATED,
)
def create_behavioral_baseline(
    payload: BaselineCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BaselineRead:
    started_at = perf_counter()
    user_id = current_user.id

    today = _utc_today()
    if payload.as_of_date > today:
        db.rollback()
        LOGGER.info(
            "Baseline creation rejected endpoint=%s error_code=%s "
            "latency_ms=%.3f",
            "/api/v1/baselines",
            "future_as_of_date",
            (perf_counter() - started_at) * 1000,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="as_of_date cannot be in the future.",
        )

    try:
        baseline = calculate_and_store_baseline(
            db,
            user_id=user_id,
            window_end=payload.as_of_date,
            window_days=payload.window_days,
            today=today,
        )
        response = BaselineRead.model_validate(baseline)
        db.commit()
    except (SQLAlchemyError, ValidationError):
        db.rollback()
        LOGGER.warning(
            "Baseline creation failed endpoint=%s error_code=%s "
            "latency_ms=%.3f",
            "/api/v1/baselines",
            "persistence_failure",
            (perf_counter() - started_at) * 1000,
        )
        raise _database_error() from None

    LOGGER.info(
        "Baseline created endpoint=%s baseline_id=%s status=%s "
        "sample_days=%d window_days=%d algorithm_version=%s latency_ms=%.3f",
        "/api/v1/baselines",
        response.id,
        response.status.value,
        response.sample_days,
        payload.window_days,
        response.algorithm_version,
        (perf_counter() - started_at) * 1000,
    )
    return response


@router.get("/latest-ready", response_model=BaselineRead)
def read_latest_ready_baseline(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BaselineRead:
    try:
        baseline = get_latest_ready_baseline(
            db,
            user_id=current_user.id,
        )
        if baseline is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ready baseline not found.",
            )
        return BaselineRead.model_validate(baseline)
    except HTTPException:
        raise
    except (SQLAlchemyError, ValidationError):
        db.rollback()
        raise _database_error() from None


@router.get("", response_model=list[BaselineRead])
def read_baseline_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    baseline_status: PersistenceBaselineStatus | None = Query(
        default=None,
        alias="status",
    ),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BaselineRead]:
    if date_from is not None and date_to is not None and date_from > date_to:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must be on or before date_to.",
        )

    try:
        baselines = list_baselines(
            db,
            user_id=current_user.id,
            status=baseline_status,
            window_end_from=date_from,
            window_end_to=date_to,
            limit=limit,
            offset=offset,
        )
        return [BaselineRead.model_validate(item) for item in baselines]
    except (SQLAlchemyError, ValidationError):
        db.rollback()
        raise _database_error() from None


__all__ = ["router"]
