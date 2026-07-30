from __future__ import annotations

import logging
from datetime import date
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_ai_service_client, get_current_user
from app.clients.ai import AIServiceClient
from app.core.database import get_db
from app.models.user import User
from app.repositories.recovery_reports import (
    get_latest_recovery_report,
    list_recovery_reports,
)
from app.schemas.recovery_report import (
    RecoveryReportCreate,
    RecoveryReportResponse,
)
from app.services.recovery_report_mapper import map_recovery_report_response
from app.services.recovery_reports import (
    RecoveryReportInputsChangedError,
    RecoveryReportInputUnavailableError,
    RiskEvaluationNotFoundError,
    generate_recovery_report_copy,
    prepare_recovery_report,
    store_prepared_recovery_report,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/recovery-reports",
    tags=["recovery-reports"],
)


def _operation_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    )


@router.post(
    "",
    response_model=RecoveryReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recovery_report(
    payload: RecoveryReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai_client: AIServiceClient = Depends(get_ai_service_client),
) -> RecoveryReportResponse:
    started_at = perf_counter()
    try:
        prepared = prepare_recovery_report(
            db,
            user_id=current_user.id,
            risk_evaluation_id=payload.risk_evaluation_id,
        )
    except RiskEvaluationNotFoundError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Risk evaluation not found.",
        ) from None
    except RecoveryReportInputUnavailableError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recovery report inputs are unavailable.",
        ) from None
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise _operation_error(
            "Recovery report inputs could not be loaded."
        ) from None

    # Authentication and source reads share this session. End that transaction
    # before waiting on the AI service. Generation failures become templates.
    db.rollback()
    try:
        content, generation_status, model_name = (
            await generate_recovery_report_copy(
                prepared,
                ai_client=ai_client,
            )
        )
    except Exception:
        db.rollback()
        LOGGER.exception("Unexpected recovery report generation failure")
        raise _operation_error(
            "Recovery report could not be generated."
        ) from None

    try:
        report = store_prepared_recovery_report(
            db,
            prepared=prepared,
            content=content,
            generation_status=generation_status,
            model_name=model_name,
        )
        response = map_recovery_report_response(report)
        db.commit()
    except (
        RecoveryReportInputsChangedError,
        RecoveryReportInputUnavailableError,
        RiskEvaluationNotFoundError,
    ):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery report inputs changed; retry generation.",
        ) from None
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise _operation_error(
            "Recovery report could not be saved."
        ) from None

    LOGGER.info(
        "Recovery report created report_id=%s risk_evaluation_id=%s "
        "generation_status=%s latency_ms=%.3f",
        response.id,
        response.risk_evaluation_id,
        response.generation_status,
        (perf_counter() - started_at) * 1000,
    )
    return response


@router.get("/latest", response_model=RecoveryReportResponse)
def read_latest_recovery_report(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecoveryReportResponse:
    try:
        report = get_latest_recovery_report(db, user_id=current_user.id)
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recovery report not found.",
            )
        return map_recovery_report_response(report)
    except HTTPException:
        raise
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise _operation_error("Recovery report could not be loaded.") from None


@router.get("", response_model=list[RecoveryReportResponse])
def read_recovery_report_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RecoveryReportResponse]:
    if date_from is not None and date_to is not None and date_from > date_to:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must be on or before date_to.",
        )
    try:
        return [
            map_recovery_report_response(report)
            for report in list_recovery_reports(
                db,
                user_id=current_user.id,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                offset=offset,
            )
        ]
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise _operation_error(
            "Recovery report history could not be loaded."
        ) from None


__all__ = ["router"]
