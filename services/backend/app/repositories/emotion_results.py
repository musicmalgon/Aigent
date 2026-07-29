from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.persistence import EmotionAnalysisResult
from app.schemas.persistence import EmotionResultCreate


def create_emotion_result(
    session: Session,
    *,
    user_id: str,
    payload: EmotionResultCreate,
) -> EmotionAnalysisResult:
    result = EmotionAnalysisResult(
        user_id=user_id,
        record_date=payload.record_date,
        analyzed_at=payload.analyzed_at,
        taxonomy_version=payload.taxonomy_version.value,
        model_version=payload.model_version,
        predicted_emotion=payload.predicted_emotion.value,
        emotion=payload.emotion.value if payload.emotion is not None else None,
        confidence=payload.confidence,
        margin=payload.margin,
        provisional=payload.provisional,
        is_uncertain=payload.is_uncertain,
        probabilities={
            label.value: probability
            for label, probability in payload.probabilities.items()
        },
        threshold_version=payload.threshold_version,
        input_hash=payload.input_hash,
    )
    session.add(result)
    session.flush()
    return result


def get_emotion_result(
    session: Session,
    *,
    user_id: str,
    result_id: str,
    for_update: bool = False,
) -> EmotionAnalysisResult | None:
    statement = select(EmotionAnalysisResult).where(
        EmotionAnalysisResult.id == result_id,
        EmotionAnalysisResult.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def get_latest_emotion_result(
    session: Session,
    *,
    user_id: str,
) -> EmotionAnalysisResult | None:
    return session.scalar(
        select(EmotionAnalysisResult)
        .where(EmotionAnalysisResult.user_id == user_id)
        .order_by(
            EmotionAnalysisResult.analyzed_at.desc(),
            EmotionAnalysisResult.created_at.desc(),
            EmotionAnalysisResult.id.desc(),
        )
        .limit(1)
    )


def get_latest_emotion_result_by_date(
    session: Session,
    *,
    user_id: str,
    record_date: date,
) -> EmotionAnalysisResult | None:
    return session.scalar(
        select(EmotionAnalysisResult)
        .where(
            EmotionAnalysisResult.user_id == user_id,
            EmotionAnalysisResult.record_date == record_date,
        )
        .order_by(
            EmotionAnalysisResult.analyzed_at.desc(),
            EmotionAnalysisResult.created_at.desc(),
            EmotionAnalysisResult.id.desc(),
        )
        .limit(1)
    )


def list_emotion_results(
    session: Session,
    *,
    user_id: str,
) -> list[EmotionAnalysisResult]:
    return list(
        session.scalars(
            select(EmotionAnalysisResult)
            .where(EmotionAnalysisResult.user_id == user_id)
            .order_by(
                EmotionAnalysisResult.analyzed_at.desc(),
                EmotionAnalysisResult.created_at.desc(),
                EmotionAnalysisResult.id.desc(),
            )
        )
    )


__all__ = [
    "create_emotion_result",
    "get_emotion_result",
    "get_latest_emotion_result",
    "get_latest_emotion_result_by_date",
    "list_emotion_results",
]
