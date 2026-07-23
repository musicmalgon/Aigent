import enum
import uuid
from sqlalchemy import Column, String, DateTime, Enum
from sqlalchemy.sql import func
from app.core.database import Base

class UserType(str, enum.Enum):
    """
        사용자 유형 — 온보딩 시 선택.
        K-BAT 초기 설문 화면에서 안내 문구를 다르게 보여주는 용도로만 쓰임
        (검사 문항/채점 로직 자체는 두 유형 모두 동일).
    """
    UNIVERSITY_STUDENT = "university_student"
    JOB_SEEKER = "job_seeker"
    EARLY_CAREER_WORKER = "early_career_worker"

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    user_type = Column(Enum(UserType), nullable=True) # 온보딩 완료 전에는 null
    created_at = Column(DateTime(timezone=True), server_default=func.now())