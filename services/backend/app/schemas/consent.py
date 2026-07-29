from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from app.models.consent import ConsentStatus, ConsentType


class ConsentGrantRequest(BaseModel):
    """동의 요청 본문 — granted_at은 법적/감사 기록이므로
    클라이언트 시계를 믿지 않고 서버에서 채운다"""

    consent_type: ConsentType
    source: str = Field(min_length=1)


class ConsentRecordRead(BaseModel):
    """DB에서 읽어온 값 — SQLite가 타임존을 날려버리므로 UTC로 간주해 보정"""

    id: str
    user_id: str
    consent_type: ConsentType
    status: ConsentStatus
    granted_at: datetime
    withdrawn_at: datetime | None = None
    source: str
    created_at: datetime

    @field_validator("granted_at", "withdrawn_at", "created_at", mode="before")
    @classmethod
    def assume_utc_if_naive(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    class Config:
        from_attributes = True
