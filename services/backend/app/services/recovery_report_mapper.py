from __future__ import annotations

from app.domain.recovery.models import (
    RecoveryAction,
    RecoveryReportCopy,
    ReportGenerationStatus,
)
from app.models.persistence import RecoveryReport
from app.schemas.recovery_report import (
    RecoveryReportFacts,
    RecoveryReportResponse,
)


def map_recovery_report_response(
    report: RecoveryReport,
) -> RecoveryReportResponse:
    return RecoveryReportResponse(
        id=report.id,
        user_id=report.user_id,
        risk_evaluation_id=report.risk_evaluation_id,
        period_start=report.period_start,
        period_end=report.period_end,
        facts=RecoveryReportFacts.model_validate(report.facts),
        selected_actions=[
            RecoveryAction.model_validate(item)
            for item in report.selected_actions
        ],
        content=RecoveryReportCopy.model_validate(report.content),
        disclaimer=report.disclaimer,
        generation_status=ReportGenerationStatus(report.generation_status),
        catalog_version=report.catalog_version,
        prompt_version=report.prompt_version,
        model_name=report.model_name,
        generated_at=report.generated_at,
        created_at=report.created_at,
    )


__all__ = ["map_recovery_report_response"]
