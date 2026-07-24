import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class UserType(StrEnum):
    """온보딩 안내 표현을 선택하는 사용자 유형."""

    UNIVERSITY_STUDENT = "university_student"
    JOB_SEEKER = "job_seeker"
    EARLY_CAREER_WORKER = "early_career_worker"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email: Mapped[str] = mapped_column(
        String,
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    user_type: Mapped[UserType | None] = mapped_column(
        Enum(UserType, name="usertype"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
