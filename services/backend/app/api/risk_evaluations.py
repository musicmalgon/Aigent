from __future__ import annotations

import logging
from datetime import date
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.repositories.risk_evaluations import (
    get_latest_dated_risk_evaluation,
    list_dated_risk_evaluations,
)
from app.schemas.risk_evaluation import (
    RiskEvaluationCreate,
    RiskEvaluationResponse,
)
from app.services.risk_evaluation import (
    DailyRecordNotFoundError,
    FutureEvaluationDateError,
    ReadyBaselineNotFoundError,
    RiskInputsChangedError,
    RiskInputUnavailableError,
    evaluate_prepared_risk,
    prepare_risk_evaluation,
    store_prepared_risk_evaluation,
)
from app.services.risk_evaluation_mapper import map_risk_evaluation_response

LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/risk-evaluations",
    tags=["risk-evaluations"],
)


def _operation_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    )


@router.post(
    "",
    response_model=RiskEvaluationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_risk_evaluation(
    payload: RiskEvaluationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RiskEvaluationResponse:
    started_at = perf_counter()
    user_id = current_user.id

    try:
        prepared = prepare_risk_evaluation(
            db,
            user_id=user_id,
            record_date=payload.date,
        )
    except DailyRecordNotFoundError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Behavioral record not found.",
        ) from None
    except FutureEvaluationDateError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date cannot be in the future for the record timezone.",
        ) from None
    except ReadyBaselineNotFoundError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A ready baseline before the evaluation date is required.",
        ) from None
    except RiskInputUnavailableError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Risk evaluation input metadata is unavailable.",
        ) from None
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise _operation_error(
            "Risk evaluation inputs could not be loaded."
        ) from None
    except Exception:
        db.rollback()
        LOGGER.exception("Unexpected risk evaluation input loading failure")
        raise _operation_error(
            "Risk evaluation inputs could not be loaded."
        ) from None

    # Authentication and all input reads use this session. End their
    # transaction before running the CPU-only rules engine.
    db.rollback()
    try:
        result = evaluate_prepared_risk(prepared)
    except (ValidationError, ValueError):
        db.rollback()
        raise _operation_error(
            "Risk evaluation could not be calculated."
        ) from None
    except Exception:
        db.rollback()
        LOGGER.exception("Unexpected risk calculation failure")
        raise _operation_error(
            "Risk evaluation could not be calculated."
        ) from None

    try:
        evaluation = store_prepared_risk_evaluation(
            db,
            prepared=prepared,
            result=result,
        )
        response = map_risk_evaluation_response(evaluation)
        db.commit()
    except RiskInputsChangedError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Risk evaluation inputs changed; retry the evaluation.",
        ) from None
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise _operation_error(
            "Risk evaluation could not be saved."
        ) from None
    except Exception:
        db.rollback()
        LOGGER.exception("Unexpected risk evaluation storage failure")
        raise _operation_error(
            "Risk evaluation could not be saved."
        ) from None

    LOGGER.info(
        "Risk evaluation created endpoint=%s evaluation_id=%s "
        "record_date=%s emotion_present=%s latency_ms=%.3f",
        "/api/v1/risk-evaluations",
        response.id,
        response.date,
        response.emotion_analysis_id is not None,
        (perf_counter() - started_at) * 1000,
    )
    return response


@router.get("/latest", response_model=RiskEvaluationResponse)
def read_latest_risk_evaluation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RiskEvaluationResponse:
    try:
        evaluation = get_latest_dated_risk_evaluation(
            db,
            user_id=current_user.id,
        )
        if evaluation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Risk evaluation not found.",
            )
        return map_risk_evaluation_response(evaluation)
    except HTTPException:
        raise
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise _operation_error(
            "Risk evaluation could not be loaded."
        ) from None


@router.get("", response_model=list[RiskEvaluationResponse])
def read_risk_evaluation_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RiskEvaluationResponse]:
    if date_from is not None and date_to is not None and date_from > date_to:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must be on or before date_to.",
        )

    try:
        evaluations = list_dated_risk_evaluations(
            db,
            user_id=current_user.id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return [
            map_risk_evaluation_response(evaluation)
            for evaluation in evaluations
        ]
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise _operation_error(
            "Risk evaluation history could not be loaded."
        ) from None


__all__ = ["router"]
