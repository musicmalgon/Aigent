from datetime import datetime, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

from app.models.assessment import AssessmentType, InterpretationScope
from app.models.user import UserType

# 앞 4개는 온보딩 초기 상태 설문(CUSTOM_INITIAL_STATE_SURVEY)용,
# 뒤 3개는 K-BAT 하위영역용. exhaustion(탈진)은 두 검사가 같은 뜻으로 쓰므로 공유한다.
DimensionKey = Literal[
    "exhaustion",
    "academic_burden",
    "occupational_burden",
    "recovery_difficulty",
    "mental_distance",
    "cognitive_control",
    "emotional_control",
]


class AssessmentAnchorBase(BaseModel):
    assessment_type: AssessmentType
    target_group: UserType
    completed_at: datetime
    dimensions: dict[DimensionKey, Optional[float]] = Field(min_length=1)
    interpretation_scope: InterpretationScope = InterpretationScope.FIXED_REFERENCE_ONLY
    source: str = Field(min_length=1)
    supersedes_id: Optional[str] = None


class AssessmentAnchorCreate(AssessmentAnchorBase):
    """사용자 입력값 — 타임존 없는 값은 명확히 거부"""

    @field_validator("completed_at")
    @classmethod
    def must_have_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("completed_at은 타임존 정보가 필요합니다 (naive datetime 불가)")
        return v


class AssessmentAnchorRead(AssessmentAnchorBase):
    """DB에서 읽어온 값 — SQLite가 타임존을 날려버리므로 UTC로 간주해 보정"""

    id: str
    user_id: str
    created_at: datetime

    @field_validator("completed_at", mode="before")
    @classmethod
    def assume_utc_if_naive(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    class Config:
        from_attributes = True