from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.risk.models import BurnoutRiskEvaluationResponse
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    EmotionAnalysisResult,
)
from app.repositories import PersistenceScopeError


def _require_user_scope(
    *,
    user_id: str,
    entity: (
        BehavioralDailyRecord
        | EmotionAnalysisResult
        | BehavioralBaseline
        | None
    ),
    entity_name: str,
) -> None:
    if entity is not None and entity.user_id != user_id:
        raise PersistenceScopeError(
            f"{entity_name} does not belong to the requested user"
        )


def create_risk_evaluation(
    session: Session,
    *,
    user_id: str,
    result: BurnoutRiskEvaluationResponse,
    daily_record: BehavioralDailyRecord | None,
    emotion_result: EmotionAnalysisResult | None,
    baseline: BehavioralBaseline | None,
    record_date: date | None = None,
    evaluated_at: datetime | None = None,
) -> BurnoutRiskEvaluation:
    _require_user_scope(
        user_id=user_id,
        entity=daily_record,
        entity_name="daily record",
    )
    _require_user_scope(
        user_id=user_id,
        entity=emotion_result,
        entity_name="emotion result",
    )
    _require_user_scope(
        user_id=user_id,
        entity=baseline,
        entity_name="baseline",
    )
    payload = result.model_dump(mode="json")
    evaluation = BurnoutRiskEvaluation(
        user_id=user_id,
        record_date=record_date or (
            daily_record.record_date if daily_record is not None else None
        ),
        evaluated_at=evaluated_at or datetime.now(UTC),
        daily_record_id=daily_record.id if daily_record is not None else None,
        emotion_analysis_result_id=(
            emotion_result.id if emotion_result is not None else None
        ),
        baseline_id=baseline.id if baseline is not None else None,
        engine_version=result.engine_version,
        score=result.score,
        level=result.level.value,
        is_provisional=result.is_provisional,
        baseline_status=result.baseline_status.value,
        data_quality=result.data_quality.value,
        category_scores=payload["category_scores"],
        factors=payload["factors"],
        summary=payload["summary"],
    )
    session.add(evaluation)
    session.flush()
    return evaluation


def get_risk_evaluation(
    session: Session,
    *,
    user_id: str,
    evaluation_id: str,
) -> BurnoutRiskEvaluation | None:
    return session.scalar(
        select(BurnoutRiskEvaluation).where(
            BurnoutRiskEvaluation.id == evaluation_id,
            BurnoutRiskEvaluation.user_id == user_id,
        )
    )


def get_latest_risk_evaluation(
    session: Session,
    *,
    user_id: str,
) -> BurnoutRiskEvaluation | None:
    return session.scalar(
        select(BurnoutRiskEvaluation)
        .where(BurnoutRiskEvaluation.user_id == user_id)
        .order_by(
            BurnoutRiskEvaluation.evaluated_at.desc(),
            BurnoutRiskEvaluation.created_at.desc(),
            BurnoutRiskEvaluation.id.desc(),
        )
        .limit(1)
    )


def list_risk_evaluations(
    session: Session,
    *,
    user_id: str,
) -> list[BurnoutRiskEvaluation]:
    return list(
        session.scalars(
            select(BurnoutRiskEvaluation)
            .where(BurnoutRiskEvaluation.user_id == user_id)
            .order_by(
                BurnoutRiskEvaluation.evaluated_at.desc(),
                BurnoutRiskEvaluation.created_at.desc(),
            )
        )
    )


__all__ = [
    "create_risk_evaluation",
    "get_latest_risk_evaluation",
    "get_risk_evaluation",
    "list_risk_evaluations",
]
