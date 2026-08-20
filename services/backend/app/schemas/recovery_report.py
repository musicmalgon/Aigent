from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from app.domain.recovery.models import (
    RecoveryAction,
    RecoveryReportChange,
    RecoveryReportCopy,
    RecoveryReportPeriod,
    ReportGenerationStatus,
)
from app.schemas.persistence import PersistenceSchema


class RecoveryReportCreate(PersistenceSchema):
    risk_evaluation_id: Annotated[str, Field(min_length=1, max_length=128)]


class RecoveryReportFacts(PersistenceSchema):
    risk_level: Literal["low", "moderate", "high", "very_high"]
    risk_score: Annotated[float, Field(ge=0, le=100)]
    is_provisional: bool
    data_quality: Literal["sufficient", "insufficient"]
    period: RecoveryReportPeriod
    changes: Annotated[list[RecoveryReportChange], Field(max_length=3)]
    stage2_signal_drivers: Annotated[list[str], Field(max_length=6)] = Field(
        default_factory=list
    )


class RecoveryReportResponse(PersistenceSchema):
    id: str
    user_id: str
    risk_evaluation_id: str
    period_start: date
    period_end: date
    facts: RecoveryReportFacts
    selected_actions: Annotated[
        list[RecoveryAction],
        Field(min_length=1, max_length=3),
    ]
    content: RecoveryReportCopy
    disclaimer: Annotated[str, Field(min_length=1, max_length=512)]
    generation_status: ReportGenerationStatus
    catalog_version: Annotated[str, Field(min_length=1, max_length=128)]
    prompt_version: Annotated[str, Field(min_length=1, max_length=128)]
    model_name: Annotated[str, Field(min_length=1, max_length=128)] | None
    generated_at: datetime
    created_at: datetime


__all__ = [
    "RecoveryReportCreate",
    "RecoveryReportFacts",
    "RecoveryReportResponse",
]
