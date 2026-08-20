from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import Field, model_validator

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


class RecoveryPlanSettingsUpdate(PersistenceSchema):
    """PATCH 바디. 필드를 아예 안 보내면(model_fields_set에 없으면) 그
    값은 건드리지 않는다 -- null을 보내는 것(지우기)과 다르다.

    target_period_start/end는 한 쌍으로만 바꿀 수 있다 -- 캘린더에서
    시작일·종료일을 같이 고르고 한 번에 저장하는 흐름과 맞춘 것이며,
    하나만 바뀌어 "시작일 > 종료일"인 중간 상태가 저장되는 걸 막는다.
    """

    notification_time: time | None = None
    target_period_start: date | None = None
    target_period_end: date | None = None

    @model_validator(mode="after")
    def validate_period_pair_and_order(self) -> RecoveryPlanSettingsUpdate:
        fields_set = self.model_fields_set
        start_given = "target_period_start" in fields_set
        end_given = "target_period_end" in fields_set
        if start_given != end_given:
            raise ValueError(
                "target_period_start and target_period_end must be set together"
            )
        if (
            self.target_period_start is not None
            and self.target_period_end is not None
            and self.target_period_start > self.target_period_end
        ):
            raise ValueError(
                "target_period_end must be on or after target_period_start"
            )
        return self


class RecoveryPlanSettingsResponse(PersistenceSchema):
    notification_time: time | None
    target_period_start: date | None
    target_period_end: date | None
    updated_at: datetime


__all__ = [
    "RecoveryPlanItemCreate",
    "RecoveryPlanItemResponse",
    "RecoveryPlanItemUpdate",
    "RecoveryPlanSettingsResponse",
    "RecoveryPlanSettingsUpdate",
]
