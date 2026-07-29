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
from app.schemas.emotion_analysis import EmotionAnalysisRead
from app.schemas.persistence import (
    EmotionLabel,
    EmotionResultCreate,
    EmotionTaxonomyVersion,
    EmotionV2Label,
)

PERSISTENCE_LABEL_BY_AI_LABEL = {
    ai_label: EmotionV2Label(ai_label.value) for ai_label in CoarseEmotionLabel
}


def map_ai_response_to_persistence(
    response: CoarseEmotionResponse,
    *,
    record_date: date,
) -> EmotionResultCreate:
    return EmotionResultCreate(
        record_date=record_date,
        analyzed_at=datetime.now(UTC),
        taxonomy_version=EmotionTaxonomyVersion.V2,
        model_version=response.model_version,
        threshold_version=response.threshold_version,
        predicted_emotion=PERSISTENCE_LABEL_BY_AI_LABEL[
            response.predicted_emotion
        ],
        emotion=(
            PERSISTENCE_LABEL_BY_AI_LABEL[response.emotion]
            if response.emotion is not None
            else None
        ),
        confidence=response.confidence,
        margin=response.margin,
        provisional=response.provisional,
        is_uncertain=response.is_uncertain,
        probabilities={
            PERSISTENCE_LABEL_BY_AI_LABEL[label]: probability
            for label, probability in response.probabilities.items()
        },
        input_hash=None,
    )


def to_emotion_analysis_read(
    result: EmotionAnalysisResult,
) -> EmotionAnalysisRead:
    if result.record_date is None:
        raise ValueError("public emotion analysis rows require record_date")
    taxonomy = EmotionTaxonomyVersion(result.taxonomy_version)
    label_type = (
        EmotionV2Label
        if taxonomy is EmotionTaxonomyVersion.V2
        else EmotionLabel
    )
    return EmotionAnalysisRead(
        id=result.id,
        user_id=result.user_id,
        record_date=result.record_date,
        analyzed_at=result.analyzed_at,
        taxonomy_version=taxonomy,
        model_version=result.model_version,
        predicted_emotion=label_type(result.predicted_emotion),
        emotion=(
            label_type(result.emotion)
            if result.emotion is not None
            else None
        ),
        confidence=result.confidence,
        margin=result.margin,
        provisional=result.provisional,
        is_uncertain=result.is_uncertain,
        probabilities={
            label_type(label): probability
            for label, probability in result.probabilities.items()
        },
        threshold_version=result.threshold_version,
        created_at=result.created_at,
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
    "to_emotion_analysis_read",
]
