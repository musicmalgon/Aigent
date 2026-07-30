from __future__ import annotations

from datetime import date, datetime

from app.domain.recovery.models import ReportGenerationStatus
from app.domain.risk.models import FactorCode, RiskLevel
from app.models.persistence import PersistenceBaselineStatus
from app.schemas.persistence import NonNegativeInteger, PersistenceSchema
from app.services.dashboard import ReadinessState


class DashboardRecordStatus(PersistenceSchema):
    today_recorded: bool
    recorded_days: NonNegativeInteger


class DashboardBaselineStatus(PersistenceSchema):
    status: PersistenceBaselineStatus
    sample_days: NonNegativeInteger
    window_end: date
    created_at: datetime


class DashboardRiskStatus(PersistenceSchema):
    level: RiskLevel
    date: date
    top_factors: list[FactorCode]


class DashboardReportStatus(PersistenceSchema):
    id: str
    headline: str
    generation_status: ReportGenerationStatus
    generated_at: datetime


class DashboardResponse(PersistenceSchema):
    record_status: DashboardRecordStatus
    baseline: DashboardBaselineStatus | None
    latest_risk: DashboardRiskStatus | None
    latest_report: DashboardReportStatus | None


class ReadinessResponse(PersistenceSchema):
    state: ReadinessState


__all__ = [
    "DashboardBaselineStatus",
    "DashboardRecordStatus",
    "DashboardReportStatus",
    "DashboardResponse",
    "DashboardRiskStatus",
    "ReadinessResponse",
]
