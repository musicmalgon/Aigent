from __future__ import annotations

from datetime import date, datetime

from pydantic import model_validator

from app.clients.ai import CoarseEmotionRequest
from app.schemas.persistence import (
    EmotionAnyLabel,
    EmotionResultCreate,
    EmotionTaxonomyVersion,
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
    predicted_emotion: EmotionAnyLabel
    emotion: EmotionAnyLabel | None
    confidence: Probability
    margin: Probability | None
    provisional: bool
    is_uncertain: bool
    probabilities: dict[EmotionAnyLabel, Probability]
    threshold_version: str | None
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
        )
        return self


__all__ = ["EmotionAnalysisCreate", "EmotionAnalysisRead"]
