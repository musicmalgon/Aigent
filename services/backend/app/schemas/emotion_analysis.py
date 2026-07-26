from __future__ import annotations

from datetime import date, datetime

from pydantic import model_validator

from app.schemas.persistence import EmotionLabel, PersistenceSchema, Probability


class EmotionAnalysisRead(PersistenceSchema):
    id: str
    user_id: str
    record_date: date | None
    analyzed_at: datetime
    model_version: str
    predicted_emotion: EmotionLabel
    confidence: Probability
    is_uncertain: bool
    probabilities: dict[EmotionLabel, Probability]
    created_at: datetime

    @model_validator(mode="after")
    def validate_probabilities(self) -> EmotionAnalysisRead:
        if set(self.probabilities) != set(EmotionLabel):
            raise ValueError("probabilities must contain exactly six emotion labels")
        if abs(sum(self.probabilities.values()) - 1.0) > 1e-6:
            raise ValueError("emotion probabilities must sum to 1 within 0.000001")
        return self


__all__ = ["EmotionAnalysisRead"]
