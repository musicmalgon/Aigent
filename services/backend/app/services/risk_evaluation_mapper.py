from __future__ import annotations

from app.domain.risk.models import BurnoutRiskEvaluationResponse
from app.models.persistence import BurnoutRiskEvaluation
from app.schemas.risk_evaluation import RiskEvaluationResponse


def map_risk_evaluation_response(
    evaluation: BurnoutRiskEvaluation,
) -> RiskEvaluationResponse:
    if evaluation.record_date is None:
        raise ValueError("a public risk evaluation must have a record date")
    if evaluation.daily_record_id is None:
        raise ValueError("a public risk evaluation must reference a daily record")

    result = BurnoutRiskEvaluationResponse.model_validate(
        {
            "score": evaluation.score,
            "level": evaluation.level,
            "is_provisional": evaluation.is_provisional,
            "baseline_status": evaluation.baseline_status,
            "data_quality": evaluation.data_quality,
            "category_scores": evaluation.category_scores,
            "factors": evaluation.factors,
            "summary": evaluation.summary,
            "engine_version": evaluation.engine_version,
        }
    )
    return RiskEvaluationResponse(
        id=evaluation.id,
        user_id=evaluation.user_id,
        date=evaluation.record_date,
        evaluated_at=evaluation.evaluated_at,
        daily_record_id=evaluation.daily_record_id,
        emotion_analysis_id=evaluation.emotion_analysis_result_id,
        baseline_id=evaluation.baseline_id,
        created_at=evaluation.created_at,
        result=result,
    )


__all__ = ["map_risk_evaluation_response"]
