from __future__ import annotations

from datetime import date, datetime

from app.domain.risk.models import BurnoutRiskEvaluationResponse
from app.schemas.behavioral_records import LocalDate
from app.schemas.persistence import PersistenceSchema


class RiskEvaluationCreate(PersistenceSchema):
    date: LocalDate


class RiskEvaluationResponse(PersistenceSchema):
    id: str
    user_id: str
    date: date
    evaluated_at: datetime
    daily_record_id: str
    emotion_analysis_id: str | None
    baseline_id: str | None
    created_at: datetime
    result: BurnoutRiskEvaluationResponse


__all__ = ["RiskEvaluationCreate", "RiskEvaluationResponse"]
