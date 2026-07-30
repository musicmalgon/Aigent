from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.dashboard import (
    DashboardBaselineStatus,
    DashboardRecordStatus,
    DashboardReportStatus,
    DashboardResponse,
    DashboardRiskStatus,
    ReadinessResponse,
)
from app.services.dashboard import (
    UserStatusSnapshot,
    classify_readiness,
    gather_user_status,
)
from app.services.recovery_report_mapper import map_recovery_report_response
from app.services.risk_evaluation_mapper import map_risk_evaluation_response

router = APIRouter(tags=["dashboard"])


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _to_dashboard_response(snapshot: UserStatusSnapshot) -> DashboardResponse:
    baseline = snapshot.latest_baseline
    evaluation = snapshot.latest_risk_evaluation
    report = snapshot.latest_recovery_report

    risk = None
    if evaluation is not None:
        mapped = map_risk_evaluation_response(evaluation)
        risk = DashboardRiskStatus(
            level=mapped.result.level,
            date=mapped.date,
            # factors는 BurnoutRiskEvaluationResponse 자체 검증자가 이미
            # contribution 내림차순을 보장하므로 앞 3개가 곧 상위 3개다.
            top_factors=[
                factor.code for factor in mapped.result.factors[:3]
            ],
        )

    latest_report = None
    if report is not None:
        mapped_report = map_recovery_report_response(report)
        latest_report = DashboardReportStatus(
            id=mapped_report.id,
            headline=mapped_report.content.headline,
            generation_status=mapped_report.generation_status,
            generated_at=mapped_report.generated_at,
        )

    return DashboardResponse(
        record_status=DashboardRecordStatus(
            today_recorded=snapshot.today_recorded,
            recorded_days=snapshot.recorded_days,
        ),
        baseline=(
            DashboardBaselineStatus.model_validate(baseline)
            if baseline is not None
            else None
        ),
        latest_risk=risk,
        latest_report=latest_report,
    )


@router.get("/api/v1/dashboard", response_model=DashboardResponse)
def read_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    snapshot = gather_user_status(
        db,
        user_id=current_user.id,
        today=_utc_today(),
    )
    return _to_dashboard_response(snapshot)


@router.get("/api/v1/readiness", response_model=ReadinessResponse)
def read_readiness(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReadinessResponse:
    snapshot = gather_user_status(
        db,
        user_id=current_user.id,
        today=_utc_today(),
    )
    return ReadinessResponse(state=classify_readiness(snapshot))


__all__ = ["router"]
