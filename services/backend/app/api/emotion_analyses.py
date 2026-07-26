from __future__ import annotations

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
    CoarseEmotionRequest,
)
from app.core.database import get_db
from app.models.user import User
from app.schemas.emotion_analysis import EmotionAnalysisRead
from app.services.emotion_analysis import analyze_and_stage_emotion_result

router = APIRouter(
    prefix="/api/v1/emotion-analyses",
    tags=["emotion-analyses"],
)


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
    payload: CoarseEmotionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai_client: AIServiceClient = Depends(get_ai_service_client),
) -> EmotionAnalysisRead:
    user_id = current_user.id

    # Authentication performs a read using this session. End that transaction
    # before waiting on the downstream service.
    db.rollback()
    try:
        result = await analyze_and_stage_emotion_result(
            db,
            user_id=user_id,
            request=payload,
            ai_client=ai_client,
        )
        response = EmotionAnalysisRead.model_validate(result)
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


__all__ = ["router"]
