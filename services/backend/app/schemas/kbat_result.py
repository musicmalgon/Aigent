from __future__ import annotations

from datetime import datetime

from app.domain.kbat import KBatRiskLevel
from app.schemas.persistence import NonNegativeInteger, PersistenceSchema
from app.services.kbat_result import KBatResultState


class KBatResultScores(PersistenceSchema):
    exhaustion_average: float
    mental_distance_average: float
    cognitive_control_average: float
    emotional_control_average: float
    total_average: float
    risk_level: KBatRiskLevel


class KBatResultResponse(PersistenceSchema):
    state: KBatResultState
    recorded_days: NonNegativeInteger
    minimum_required_days: NonNegativeInteger
    survey_completed_at: datetime | None
    result: KBatResultScores | None


__all__ = ["KBatResultResponse", "KBatResultScores"]
