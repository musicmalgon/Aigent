from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.persistence import (
        BehavioralBaseline,
        BehavioralDailyRecord,
        BurnoutRiskEvaluation,
        EmotionAnalysisResult,
    )


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
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    user_type: Mapped[UserType | None] = mapped_column(
        Enum(UserType, name="usertype"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    daily_records: Mapped[list[BehavioralDailyRecord]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    emotion_results: Mapped[list[EmotionAnalysisResult]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    behavioral_baselines: Mapped[list[BehavioralBaseline]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    risk_evaluations: Mapped[list[BurnoutRiskEvaluation]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )