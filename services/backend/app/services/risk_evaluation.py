from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.risk.engine import BurnoutRiskEngine
from app.domain.risk.models import BurnoutRiskEvaluationResponse
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    EmotionAnalysisResult,
)
from app.repositories.risk_evaluations import create_risk_evaluation
from app.services.risk_adapter import build_risk_request


def evaluate_and_store(
    session: Session,
    *,
    user_id: str,
    daily_record: BehavioralDailyRecord,
    emotion_result: EmotionAnalysisResult | None,
    baseline: BehavioralBaseline | None,
    engine: BurnoutRiskEngine | None = None,
) -> tuple[BurnoutRiskEvaluation, BurnoutRiskEvaluationResponse]:
    request = build_risk_request(
        user_id=user_id,
        daily_record=daily_record,
        emotion_result=emotion_result,
        baseline=baseline,
    )
    result = (engine or BurnoutRiskEngine()).evaluate(request)
    evaluation = create_risk_evaluation(
        session,
        user_id=user_id,
        result=result,
        daily_record=daily_record,
        emotion_result=emotion_result,
        baseline=baseline,
    )
    return evaluation, result


__all__ = ["evaluate_and_store"]
