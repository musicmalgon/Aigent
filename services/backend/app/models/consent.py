import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class ConsentType(str, enum.Enum):
    # 온보딩 동의 화면(Consent.tsx) 5개 항목과 1:1로 대응한다. 예전엔 이 중
    # health_data/emotion_diary 2개만 실제로 저장되고 나머지 3개(이용약관,
    # 개인정보 수집, 외부 서비스 연동)는 화면 체크박스 상태로만 관리돼서,
    # 동의내역 화면이 사용자가 실제로 고른 것과 무관하게 항상 "가입 시
    # 동의"라고 표시했다 -- 특히 선택 항목은 체크 안 해도 그렇게 표시돼서
    # 실제 선택과 정반대로 보였다(#H1).
    TERMS_OF_SERVICE = "terms_of_service"
    PRIVACY_POLICY = "privacy_policy"
    HEALTH_DATA = "health_data"
    EMOTION_DIARY = "emotion_diary"
    # 가입 화면(Consent.tsx)이 체크박스 5개를 보여주면서도 실제로는 이
    # 2개만 서버에 저장했었다 -- 나머지 3개는 사용자가 체크해도 다음
    # 화면으로 넘어가는 순간 사라졌다. 아래 3개를 추가해 5개 항목 전부
    # 실제 동의 이력으로 남긴다.
    TERMS_OF_SERVICE = "terms_of_service"
    PRIVACY_POLICY = "privacy_policy"
    EXTERNAL_INTEGRATION = "external_integration"


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
