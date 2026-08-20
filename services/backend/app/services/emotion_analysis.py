from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.clients.ai import (
    AIServiceClient,
    AIServiceError,
    BurnoutSignalResponse,
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
    NeutralGateDecision,
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
        predicted_emotion=(
            PERSISTENCE_LABEL_BY_AI_LABEL[response.predicted_emotion]
            if response.predicted_emotion is not None
            else None
        ),
        emotion=(
            PERSISTENCE_LABEL_BY_AI_LABEL[response.emotion]
            if response.emotion is not None
            else None
        ),
        confidence=response.confidence,
        margin=response.margin,
        provisional=response.provisional,
        is_uncertain=response.is_uncertain,
        probabilities=(
            {
                PERSISTENCE_LABEL_BY_AI_LABEL[label]: probability
                for label, probability in response.probabilities.items()
            }
            if response.probabilities is not None
            else None
        ),
        neutral_gate_decision=(
            NeutralGateDecision(response.neutral_gate_decision.value)
            if response.neutral_gate_decision is not None
            else None
        ),
        neutral_gate_score=response.neutral_gate_score,
        neutral_gate_model_version=response.neutral_gate_model_version,
        neutral_gate_threshold=response.neutral_gate_threshold,
        input_hash=None,
    )


def to_emotion_analysis_read(
    result: EmotionAnalysisResult,
) -> EmotionAnalysisRead:
    if result.record_date is None:
        raise ValueError("public emotion analysis rows require record_date")
    taxonomy = EmotionTaxonomyVersion(result.taxonomy_version)
    label_type = (
        EmotionV2Label if taxonomy is EmotionTaxonomyVersion.V2 else EmotionLabel
    )
    mapped_probabilities: (
        Mapping[EmotionLabel, float]
        | Mapping[EmotionV2Label, float]
        | None
    )
    if result.probabilities is None:
        mapped_probabilities = None
    elif taxonomy is EmotionTaxonomyVersion.V2:
        mapped_probabilities = {
            EmotionV2Label(label): probability
            for label, probability in result.probabilities.items()
        }
    else:
        mapped_probabilities = {
            EmotionLabel(label): probability
            for label, probability in result.probabilities.items()
        }
    return EmotionAnalysisRead(
        id=result.id,
        user_id=result.user_id,
        record_date=result.record_date,
        analyzed_at=result.analyzed_at,
        taxonomy_version=taxonomy,
        model_version=result.model_version,
        predicted_emotion=(
            label_type(result.predicted_emotion)
            if result.predicted_emotion is not None
            else None
        ),
        emotion=(label_type(result.emotion) if result.emotion is not None else None),
        confidence=result.confidence,
        margin=result.margin,
        provisional=result.provisional,
        is_uncertain=result.is_uncertain,
        probabilities=mapped_probabilities,
        threshold_version=result.threshold_version,
        neutral_gate_decision=(
            NeutralGateDecision(result.neutral_gate_decision)
            if result.neutral_gate_decision is not None
            else None
        ),
        neutral_gate_score=result.neutral_gate_score,
        neutral_gate_model_version=result.neutral_gate_model_version,
        neutral_gate_threshold=result.neutral_gate_threshold,
        created_at=result.created_at,
    )


def _map_burnout_signal_payload(
    response: BurnoutSignalResponse,
) -> dict[str, object]:
    """Persist structured Stage 2 provenance without storing diary text."""

    return response.model_dump(mode="json")


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
    # Stage 2 is fail-open: a missing local artifact must not block the
    # ordinary emotion diary. When available, its output is persisted for
    # recovery-plan ranking (validated labels only are consumed downstream).
    analyze_burnout_signals = getattr(ai_client, "analyze_burnout_signals", None)
    if (
        getattr(ai_client, "stage2_burnout_signals_enabled", False)
        and analyze_burnout_signals is not None
    ):
        try:
            burnout_response = await analyze_burnout_signals(request)
        except AIServiceError:
            burnout_response = None
        if burnout_response is not None:
            payload.burnout_signal_payload = _map_burnout_signal_payload(
                burnout_response
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
