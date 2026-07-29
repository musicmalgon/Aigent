import enum
import uuid
from sqlalchemy import Column, String, DateTime, Enum, JSON, ForeignKey, func
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.user import UserType  # 새로 만들지 않고 재사용


class AssessmentType(str, enum.Enum):
    CUSTOM_INITIAL_STATE_SURVEY = "custom_initial_state_survey"
    K_BAT = "k_bat"


class InterpretationScope(str, enum.Enum):
    FIXED_REFERENCE_ONLY = "fixed_reference_only"


class AssessmentAnchor(Base):
    __tablename__ = "assessment_anchors"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    assessment_type = Column(Enum(AssessmentType), nullable=False)
    target_group = Column(Enum(UserType), nullable=False)  # UserType 재사용
    completed_at = Column(DateTime(timezone=True), nullable=False)  # 사용자가 설문 완료한 시각(자가보고)

    # dimensions는 키가 4개 enum으로 제한되지만 값은 null 허용 -> JSON으로 원본 그대로 보존
    dimensions = Column(JSON, nullable=False)

    interpretation_scope = Column(
        Enum(InterpretationScope), nullable=False,
        default=InterpretationScope.FIXED_REFERENCE_ONLY
    )
    source = Column(String, nullable=False)

    # 정정/교체 추적용 — 새 검사가 이전 검사를 대체하면 이전 것의 id를 가리킴
    supersedes_id = Column(String, ForeignKey("assessment_anchors.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)  # 서버 저장 시각

    user = relationship("User", backref="assessment_anchors")
    supersedes = relationship("AssessmentAnchor", remote_side=[id])