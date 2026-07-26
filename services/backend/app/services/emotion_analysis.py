from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.clients.ai import (
    AIServiceClient,
    CoarseEmotionLabel,
    CoarseEmotionRequest,
    CoarseEmotionResponse,
)
from app.models.persistence import EmotionAnalysisResult
from app.repositories import emotion_results
from app.schemas.persistence import EmotionLabel, EmotionResultCreate

PERSISTENCE_LABEL_BY_AI_LABEL = {
    ai_label: EmotionLabel(ai_label.value) for ai_label in CoarseEmotionLabel
}


def map_ai_response_to_persistence(
    response: CoarseEmotionResponse,
    *,
    record_date: date,
) -> EmotionResultCreate:
    return EmotionResultCreate(
        record_date=record_date,
        analyzed_at=datetime.now(UTC),
        model_version=response.model_version,
        predicted_emotion=PERSISTENCE_LABEL_BY_AI_LABEL[
            response.predicted_emotion
        ],
        confidence=response.confidence,
        is_uncertain=response.is_uncertain,
        probabilities={
            PERSISTENCE_LABEL_BY_AI_LABEL[label]: probability
            for label, probability in response.probabilities.items()
        },
        input_hash=None,
    )


async def analyze_and_stage_emotion_result(
    session: Session,
    *,
    user_id: str,
    record_date: date,
    request: CoarseEmotionRequest,
    ai_client: AIServiceClient,
) -> EmotionAnalysisResult:
    response = await ai_client.classify_emotion(request)
    payload = map_ai_response_to_persistence(
        response,
        record_date=record_date,
    )
    return emotion_results.create_emotion_result(
        session,
        user_id=user_id,
        payload=payload,
    )


__all__ = [
    "PERSISTENCE_LABEL_BY_AI_LABEL",
    "analyze_and_stage_emotion_result",
    "map_ai_response_to_persistence",
]
