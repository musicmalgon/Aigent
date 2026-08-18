from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.recovery.catalog import CATALOG_VERSION
from app.domain.recovery.models import (
    RecoveryReportCopy,
    RecoveryReportGenerationRequest,
    ReportGenerationStatus,
)
from app.models.persistence import BurnoutRiskEvaluation, RecoveryReport


def create_recovery_report(
    session: Session,
    *,
    user_id: str,
    risk_evaluation: BurnoutRiskEvaluation,
    request: RecoveryReportGenerationRequest,
    content: RecoveryReportCopy,
    generation_status: ReportGenerationStatus,
    model_name: str | None,
    disclaimer: str,
    generated_at: datetime | None = None,
) -> RecoveryReport:
    if risk_evaluation.user_id != user_id:
        raise ValueError("risk evaluation does not belong to user")
    facts = request.model_dump(
        mode="json",
        exclude={"selected_actions", "prompt_version"},
    )
    report = RecoveryReport(
        user_id=user_id,
        risk_evaluation_id=risk_evaluation.id,
        period_start=request.period.start,
        period_end=request.period.end,
        facts=facts,
        selected_actions=[
            action.model_dump(mode="json")
            for action in request.selected_actions
        ],
        content=content.model_dump(mode="json"),
        disclaimer=disclaimer,
        generation_status=generation_status.value,
        catalog_version=CATALOG_VERSION,
        prompt_version=request.prompt_version,
        model_name=model_name,
        generated_at=generated_at or datetime.now(UTC),
    )
    session.add(report)
    session.flush()
    return report


def get_recovery_report(
    session: Session,
    *,
    user_id: str,
    report_id: str,
) -> RecoveryReport | None:
    return session.scalar(
        select(RecoveryReport).where(
            RecoveryReport.id == report_id,
            RecoveryReport.user_id == user_id,
        )
    )


def get_latest_recovery_report(
    session: Session,
    *,
    user_id: str,
) -> RecoveryReport | None:
    return session.scalar(
        select(RecoveryReport)
        .where(RecoveryReport.user_id == user_id)
        .order_by(
            RecoveryReport.generated_at.desc(),
            RecoveryReport.created_at.desc(),
            RecoveryReport.id.desc(),
        )
        .limit(1)
    )


def list_recovery_reports(
    session: Session,
    *,
    user_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[RecoveryReport]:
    statement = select(RecoveryReport).where(
        RecoveryReport.user_id == user_id
    )
    if date_from is not None:
        statement = statement.where(RecoveryReport.period_end >= date_from)
    if date_to is not None:
        statement = statement.where(RecoveryReport.period_end <= date_to)
    statement = (
        statement.order_by(
            RecoveryReport.generated_at.desc(),
            RecoveryReport.created_at.desc(),
            RecoveryReport.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(statement))


__all__ = [
    "create_recovery_report",
    "get_latest_recovery_report",
    "get_recovery_report",
    "list_recovery_reports",
]
