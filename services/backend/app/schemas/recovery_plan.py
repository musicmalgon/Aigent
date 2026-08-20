from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.persistence import PersistenceSchema


class RecoveryPlanItemCreate(PersistenceSchema):
    action_id: Annotated[str, Field(min_length=1, max_length=64)]
    source_report_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None


class RecoveryPlanItemUpdate(PersistenceSchema):
    status: Literal["planned", "completed"]


class RecoveryPlanItemResponse(PersistenceSchema):
    id: str
    user_id: str
    source_report_id: str | None
    action_id: str
    title: str
    duration_minutes: int | None
    difficulty: Literal["easy", "medium"]
    status: Literal["planned", "completed"]
    selected_at: datetime
    completed_at: datetime | None


__all__ = [
    "RecoveryPlanItemCreate",
    "RecoveryPlanItemResponse",
    "RecoveryPlanItemUpdate",
]
