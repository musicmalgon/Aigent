from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime

from pydantic import model_validator

from app.clients.ai import CoarseEmotionRequest
from app.schemas.persistence import (
    EmotionAnyLabel,
    EmotionLabel,
    EmotionResultCreate,
    EmotionTaxonomyVersion,
    EmotionV2Label,
    NeutralGateDecision,
    PersistenceSchema,
    Probability,
)


class EmotionAnalysisCreate(CoarseEmotionRequest):
    record_date: date

    def to_ai_request(self) -> CoarseEmotionRequest:
        return CoarseEmotionRequest(
            hs01=self.hs01,
            hs02=self.hs02,
            hs03=self.hs03,
        )


class EmotionAnalysisRead(PersistenceSchema):
    id: str
    user_id: str
    record_date: date
    analyzed_at: datetime
    taxonomy_version: EmotionTaxonomyVersion
    model_version: str
    predicted_emotion: EmotionAnyLabel | None
    emotion: EmotionAnyLabel | None
    confidence: Probability | None
    margin: Probability | None
    provisional: bool
    is_uncertain: bool
    probabilities: (
        Mapping[EmotionLabel, Probability]
        | Mapping[EmotionV2Label, Probability]
        | None
    )
    threshold_version: str | None
    neutral_gate_decision: NeutralGateDecision | None
    neutral_gate_score: Probability | None
    neutral_gate_model_version: str | None
    neutral_gate_threshold: Probability | None
    created_at: datetime

    @model_validator(mode="after")
    def validate_contract(self) -> EmotionAnalysisRead:
        EmotionResultCreate(
            record_date=self.record_date,
            analyzed_at=self.analyzed_at,
            taxonomy_version=self.taxonomy_version,
            model_version=self.model_version,
            predicted_emotion=self.predicted_emotion,
            emotion=self.emotion,
            confidence=self.confidence,
            margin=self.margin,
            provisional=self.provisional,
            is_uncertain=self.is_uncertain,
            probabilities=self.probabilities,
            threshold_version=self.threshold_version,
            neutral_gate_decision=self.neutral_gate_decision,
            neutral_gate_score=self.neutral_gate_score,
            neutral_gate_model_version=self.neutral_gate_model_version,
            neutral_gate_threshold=self.neutral_gate_threshold,
        )
        return self


__all__ = ["EmotionAnalysisCreate", "EmotionAnalysisRead"]
