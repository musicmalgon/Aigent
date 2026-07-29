from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_ai_service_client, get_current_user
from app.clients.ai import (
    AIServiceClient,
    AIServiceClientResponseError,
    AIServiceConfigurationError,
    AIServiceConnectionError,
    AIServiceError,
    AIServiceTimeoutError,
)
from app.core.database import get_db
from app.models.user import User
from app.repositories.behavioral_records import get_daily_record_by_date
from app.repositories.emotion_results import (
    get_emotion_result,
    get_latest_emotion_result,
    list_emotion_results,
)
from app.schemas.emotion_analysis import (
    EmotionAnalysisCreate,
    EmotionAnalysisRead,
)
from app.services.emotion_analysis import (
    analyze_and_stage_emotion_result,
    to_emotion_analysis_read,
)

router = APIRouter(
    prefix="/api/v1/emotion-analyses",
    tags=["emotion-analyses"],
)


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _downstream_error(exc: AIServiceError) -> HTTPException:
    if isinstance(exc, AIServiceTimeoutError):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Emotion analysis service timed out.",
        )
    if isinstance(
        exc,
        (AIServiceConnectionError, AIServiceConfigurationError),
    ):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Emotion analysis service is unavailable.",
        )
    if isinstance(exc, AIServiceClientResponseError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Emotion analysis service rejected the request.",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Emotion analysis service returned an invalid response.",
    )


@router.post(
    "",
    response_model=EmotionAnalysisRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_emotion_analysis(
    payload: EmotionAnalysisCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai_client: AIServiceClient = Depends(get_ai_service_client),
) -> EmotionAnalysisRead:
    user_id = current_user.id

    if payload.record_date > _utc_today():
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="record_date cannot be in the future.",
        )

    try:
        daily_record = get_daily_record_by_date(
            db,
            user_id=user_id,
            record_date=payload.record_date,
        )
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Behavioral record could not be verified.",
        ) from None

    if daily_record is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Behavioral record not found.",
        )

    # Authentication and ownership verification perform reads using this
    # session. End that transaction before waiting on the downstream service.
    db.rollback()
    try:
        result = await analyze_and_stage_emotion_result(
            db,
            user_id=user_id,
            record_date=payload.record_date,
            request=payload.to_ai_request(),
            ai_client=ai_client,
        )
        response = to_emotion_analysis_read(result)
        db.commit()
    except AIServiceError as exc:
        db.rollback()
        raise _downstream_error(exc) from exc
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Emotion analysis service returned an invalid response.",
        ) from exc
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Emotion analysis could not be saved.",
        ) from None

    return response


@router.get("", response_model=list[EmotionAnalysisRead])
def read_emotion_analyses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EmotionAnalysisRead]:
    return [
        to_emotion_analysis_read(result)
        for result in list_emotion_results(db, user_id=current_user.id)
    ]


@router.get("/latest", response_model=EmotionAnalysisRead)
def read_latest_emotion_analysis(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmotionAnalysisRead:
    result = get_latest_emotion_result(db, user_id=current_user.id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No emotion analysis results found.",
        )
    return to_emotion_analysis_read(result)


@router.get("/{result_id}", response_model=EmotionAnalysisRead)
def read_emotion_analysis(
    result_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmotionAnalysisRead:
    result = get_emotion_result(
        db,
        user_id=current_user.id,
        result_id=result_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Emotion analysis result not found.",
        )
    return to_emotion_analysis_read(result)


__all__ = ["router"]
