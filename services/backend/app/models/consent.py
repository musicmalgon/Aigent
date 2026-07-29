import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class ConsentType(str, enum.Enum):
    HEALTH_DATA = "health_data"
    EMOTION_DIARY = "emotion_diary"


class ConsentStatus(str, enum.Enum):
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


class ConsentRecord(Base):
    """동의/철회 이력 — 행위마다 새 행을 추가하고 (user_id, consent_type)의
    최신 created_at 행이 현재 상태다. 감사 추적을 위해 기존 행은 갱신하지 않는다."""

    __tablename__ = "consent_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    consent_type = Column(Enum(ConsentType), nullable=False)
    status = Column(Enum(ConsentStatus), nullable=False)

    # 철회 행에서도 원래 동의 시각을 그대로 옮겨 담아 동의 시점이 유실되지 않게 한다
    granted_at = Column(DateTime(timezone=True), nullable=False)
    withdrawn_at = Column(DateTime(timezone=True), nullable=True)

    source = Column(String, nullable=False)

    # SQLite의 CURRENT_TIMESTAMP는 초 단위라 같은 초에 동의->철회가 들어오면 순서가
    # 모호해진다. behavioral_baselines처럼 파이썬 기본값(마이크로초)을 함께 두어
    # "최신 행" 판정을 결정적으로 만든다.
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    user = relationship("User", backref="consent_records")
