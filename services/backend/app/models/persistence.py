from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.types import ArbitraryInteger, StrictJSON, UTCDateTime

if TYPE_CHECKING:
    from app.models.user import User


def _uuid() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_type]


class DailyRecordSource(StrEnum):
    MANUAL = "manual"
    CALENDAR = "calendar"
    HEALTH_CONNECT = "health_connect"
    IMPORTED = "imported"


class PersistenceBaselineStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT = "insufficient"


class BehavioralDailyRecord(Base):
    __tablename__ = "behavioral_daily_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "record_date",
            name="uq_behavioral_daily_records_user_date",
        ),
        CheckConstraint(
            "sleep_minutes IS NULL OR "
            "(sleep_minutes >= 0 AND sleep_minutes <= 1440)",
            name="ck_daily_sleep_minutes",
        ),
        CheckConstraint(
            "steps IS NULL OR CAST(steps AS NUMERIC) >= 0",
            name="ck_daily_steps",
        ),
        CheckConstraint(
            "active_minutes IS NULL OR "
            "(active_minutes >= 0 AND active_minutes <= 1440)",
            name="ck_daily_active_minutes",
        ),
        CheckConstraint(
            "study_work_minutes IS NULL OR "
            "(study_work_minutes >= 0 AND study_work_minutes <= 1440)",
            name="ck_daily_study_work_minutes",
        ),
        CheckConstraint(
            "rest_minutes IS NULL OR "
            "(rest_minutes >= 0 AND rest_minutes <= 1440)",
            name="ck_daily_rest_minutes",
        ),
        CheckConstraint(
            "exercise_minutes IS NULL OR "
            "(exercise_minutes >= 0 AND exercise_minutes <= 1440)",
            name="ck_daily_exercise_minutes",
        ),
        CheckConstraint(
            "schedule_count IS NULL OR CAST(schedule_count AS NUMERIC) >= 0",
            name="ck_daily_schedule_count",
        ),
        CheckConstraint(
            "subjective_stress IS NULL OR "
            "(subjective_stress >= 0 AND subjective_stress <= 10)",
            name="ck_daily_subjective_stress",
        ),
        CheckConstraint(
            "subjective_fatigue IS NULL OR subjective_fatigue >= 0",
            name="ck_daily_subjective_fatigue",
        ),
        CheckConstraint(
            "data_completeness IS NULL OR "
            "(data_completeness >= 0 AND data_completeness <= 1)",
            name="ck_daily_data_completeness",
        ),
        CheckConstraint(
            "length(trim(timezone)) > 0",
            name="ck_daily_timezone_nonempty",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    sleep_minutes: Mapped[int | None] = mapped_column(Integer)
    bedtime: Mapped[time | None] = mapped_column(Time(timezone=False))
    wake_time: Mapped[time | None] = mapped_column(Time(timezone=False))
    steps: Mapped[int | None] = mapped_column(ArbitraryInteger())
    active_minutes: Mapped[int | None] = mapped_column(Integer)
    study_work_minutes: Mapped[int | None] = mapped_column(Integer)
    rest_minutes: Mapped[int | None] = mapped_column(Integer)
    exercise_minutes: Mapped[int | None] = mapped_column(Integer)
    schedule_count: Mapped[int | None] = mapped_column(ArbitraryInteger())
    subjective_stress: Mapped[float | None] = mapped_column(Float)
    subjective_fatigue: Mapped[float | None] = mapped_column(Float)
    source: Mapped[DailyRecordSource] = mapped_column(
        Enum(
            DailyRecordSource,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="daily_record_source",
        ),
        default=DailyRecordSource.MANUAL,
        server_default=DailyRecordSource.MANUAL.value,
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        server_default="UTC",
        nullable=False,
    )
    data_completeness: Mapped[float | None] = mapped_column(Float)
    source_by_field: Mapped[dict[str, str] | None] = mapped_column(StrictJSON())
    coverage_by_field: Mapped[dict[str, str] | None] = mapped_column(StrictJSON())
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=_utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="daily_records")
    risk_evaluations: Mapped[list[BurnoutRiskEvaluation]] = relationship(
        back_populates="daily_record",
        passive_deletes=True,
    )


class EmotionAnalysisResult(Base):
    __tablename__ = "emotion_analysis_results"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_emotion_confidence",
        ),
        CheckConstraint(
            "length(trim(model_version)) > 0",
            name="ck_emotion_model_version_nonempty",
        ),
        CheckConstraint(
            "input_hash IS NULL OR length(trim(input_hash)) > 0",
            name="ck_emotion_input_hash_nonempty",
        ),
        CheckConstraint(
            "("
            "taxonomy_version = 'v1' "
            "AND predicted_emotion IN "
            "('기쁨', '불안', '당황', '분노', '슬픔', '상처') "
            "AND emotion = predicted_emotion "
            "AND provisional = 0 "
            "AND confidence IS NOT NULL "
            "AND probabilities IS NOT NULL "
            "AND margin IS NULL "
            "AND threshold_version IS NULL "
            "AND neutral_gate_decision IS NULL "
            "AND neutral_gate_score IS NULL "
            "AND neutral_gate_model_version IS NULL "
            "AND neutral_gate_threshold IS NULL"
            ") OR ("
            "taxonomy_version = 'v2' "
            "AND threshold_version IS NOT NULL "
            "AND length(trim(threshold_version)) > 0 "
            "AND ("
            "("
            "neutral_gate_decision = 'neutral' "
            "AND predicted_emotion IS NULL "
            "AND emotion IS NULL "
            "AND confidence IS NULL "
            "AND margin IS NULL "
            "AND probabilities IS NULL "
            "AND provisional = 1 "
            "AND is_uncertain = 1"
            ") OR ("
            "predicted_emotion IN "
            "('분노', '기쁨', '불안', '당황', '슬픔', '무기력') "
            "AND confidence IS NOT NULL "
            "AND margin IS NOT NULL "
            "AND probabilities IS NOT NULL "
            "AND provisional = is_uncertain "
            "AND ("
            "(provisional = 1 AND emotion IS NULL) "
            "OR (provisional = 0 AND emotion = predicted_emotion)"
            ")"
            ")"
            ")"
            ")",
            name="ck_emotion_taxonomy_payload",
        ),
        CheckConstraint(
            "("
            "neutral_gate_decision IS NULL "
            "AND neutral_gate_score IS NULL "
            "AND neutral_gate_model_version IS NULL "
            "AND neutral_gate_threshold IS NULL"
            ") OR ("
            "neutral_gate_decision IN ('neutral', 'emotional') "
            "AND neutral_gate_score IS NOT NULL "
            "AND neutral_gate_score >= 0 AND neutral_gate_score <= 1 "
            "AND neutral_gate_model_version IS NOT NULL "
            "AND length(trim(neutral_gate_model_version)) > 0 "
            "AND neutral_gate_threshold IS NOT NULL "
            "AND neutral_gate_threshold >= 0 AND neutral_gate_threshold <= 1 "
            "AND ("
            "(neutral_gate_decision = 'neutral' "
            "AND (1 - neutral_gate_score) < neutral_gate_threshold) "
            "OR (neutral_gate_decision = 'emotional' "
            "AND (1 - neutral_gate_score) >= neutral_gate_threshold)"
            ")"
            ")",
            name="ck_emotion_neutral_gate_provenance",
        ),
        CheckConstraint(
            "margin IS NULL OR (margin >= 0 AND margin <= 1)",
            name="ck_emotion_margin",
        ),
        Index(
            "ix_emotion_results_user_analyzed_at",
            "user_id",
            "analyzed_at",
        ),
        Index(
            "ix_emotion_results_user_record_date_analyzed_at",
            "user_id",
            "record_date",
            "analyzed_at",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_date: Mapped[date | None] = mapped_column(Date)
    analyzed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=_utc_now,
        nullable=False,
    )
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(
        String(16),
        default="v1",
        server_default="v1",
        nullable=False,
    )
    predicted_emotion: Mapped[str | None] = mapped_column(String(16))
    emotion: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float)
    is_uncertain: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    probabilities: Mapped[dict[str, float] | None] = mapped_column(
        StrictJSON(none_as_null=True)
    )
    margin: Mapped[float | None] = mapped_column(Float)
    provisional: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    threshold_version: Mapped[str | None] = mapped_column(String(64))
    neutral_gate_decision: Mapped[str | None] = mapped_column(String(16))
    neutral_gate_score: Mapped[float | None] = mapped_column(Float)
    neutral_gate_model_version: Mapped[str | None] = mapped_column(String(128))
    neutral_gate_threshold: Mapped[float | None] = mapped_column(Float)
    input_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=_utc_now,
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="emotion_results")
    risk_evaluations: Mapped[list[BurnoutRiskEvaluation]] = relationship(
        back_populates="emotion_analysis_result",
        passive_deletes=True,
    )


class BehavioralBaseline(Base):
    __tablename__ = "behavioral_baselines"
    __table_args__ = (
        CheckConstraint(
            "window_start <= window_end",
            name="ck_baseline_window_order",
        ),
        CheckConstraint("sample_days >= 0", name="ck_baseline_sample_days"),
        CheckConstraint(
            "sleep_minutes IS NULL OR "
            "(sleep_minutes >= 0 AND sleep_minutes <= 1440)",
            name="ck_baseline_sleep_minutes",
        ),
        CheckConstraint(
            "study_work_minutes IS NULL OR "
            "(study_work_minutes >= 0 AND study_work_minutes <= 1440)",
            name="ck_baseline_study_work_minutes",
        ),
        CheckConstraint(
            "rest_minutes IS NULL OR "
            "(rest_minutes >= 0 AND rest_minutes <= 1440)",
            name="ck_baseline_rest_minutes",
        ),
        CheckConstraint(
            "exercise_minutes IS NULL OR "
            "(exercise_minutes >= 0 AND exercise_minutes <= 1440)",
            name="ck_baseline_exercise_minutes",
        ),
        CheckConstraint(
            "schedule_count IS NULL OR schedule_count >= 0",
            name="ck_baseline_schedule_count",
        ),
        CheckConstraint(
            "subjective_stress IS NULL OR "
            "(subjective_stress >= 0 AND subjective_stress <= 10)",
            name="ck_baseline_subjective_stress",
        ),
        CheckConstraint(
            "subjective_fatigue IS NULL OR subjective_fatigue >= 0",
            name="ck_baseline_subjective_fatigue",
        ),
        CheckConstraint(
            "negative_emotion_probability IS NULL OR "
            "(negative_emotion_probability >= 0 "
            "AND negative_emotion_probability <= 1)",
            name="ck_baseline_negative_emotion_probability",
        ),
        CheckConstraint(
            "length(trim(algorithm_version)) > 0",
            name="ck_baseline_algorithm_version_nonempty",
        ),
        Index(
            "ix_behavioral_baselines_user_window_end",
            "user_id",
            "window_end",
        ),
        Index(
            "ix_behavioral_baselines_user_status_window_end",
            "user_id",
            "status",
            "window_end",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    sample_days: Mapped[int] = mapped_column(Integer, nullable=False)
    sleep_minutes: Mapped[float | None] = mapped_column(Float)
    study_work_minutes: Mapped[float | None] = mapped_column(Float)
    rest_minutes: Mapped[float | None] = mapped_column(Float)
    exercise_minutes: Mapped[float | None] = mapped_column(Float)
    schedule_count: Mapped[float | None] = mapped_column(Float)
    subjective_stress: Mapped[float | None] = mapped_column(Float)
    subjective_fatigue: Mapped[float | None] = mapped_column(Float)
    negative_emotion_probability: Mapped[float | None] = mapped_column(Float)
    status: Mapped[PersistenceBaselineStatus] = mapped_column(
        Enum(
            PersistenceBaselineStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="persistence_baseline_status",
        ),
        nullable=False,
    )
    algorithm_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=_utc_now,
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="behavioral_baselines")
    risk_evaluations: Mapped[list[BurnoutRiskEvaluation]] = relationship(
        back_populates="baseline",
        passive_deletes=True,
    )


class BurnoutRiskEvaluation(Base):
    __tablename__ = "burnout_risk_evaluations"
    __table_args__ = (
        CheckConstraint(
            "score >= 0 AND score <= 100",
            name="ck_risk_evaluation_score",
        ),
        CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_risk_evaluation_engine_version_nonempty",
        ),
        CheckConstraint(
            "level IN ('low', 'moderate', 'high', 'very_high')",
            name="ck_risk_evaluation_level",
        ),
        CheckConstraint(
            "baseline_status IN ('ready', 'insufficient', 'missing')",
            name="ck_risk_evaluation_baseline_status",
        ),
        CheckConstraint(
            "data_quality IN ('sufficient', 'insufficient')",
            name="ck_risk_evaluation_data_quality",
        ),
        Index(
            "ix_risk_evaluations_user_evaluated_at",
            "user_id",
            "evaluated_at",
        ),
        Index(
            "ix_risk_evaluations_user_record_date",
            "user_id",
            "record_date",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_date: Mapped[date | None] = mapped_column(Date)
    evaluated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=_utc_now,
        nullable=False,
    )
    daily_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("behavioral_daily_records.id", ondelete="SET NULL")
    )
    emotion_analysis_result_id: Mapped[str | None] = mapped_column(
        ForeignKey("emotion_analysis_results.id", ondelete="SET NULL")
    )
    baseline_id: Mapped[str | None] = mapped_column(
        ForeignKey("behavioral_baselines.id", ondelete="SET NULL")
    )
    engine_version: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    is_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False)
    baseline_status: Mapped[str] = mapped_column(String(32), nullable=False)
    data_quality: Mapped[str] = mapped_column(String(32), nullable=False)
    category_scores: Mapped[dict[str, float]] = mapped_column(
        StrictJSON(),
        nullable=False,
    )
    factors: Mapped[list[dict[str, Any]]] = mapped_column(
        StrictJSON(),
        nullable=False,
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        StrictJSON(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=_utc_now,
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="risk_evaluations")
    daily_record: Mapped[BehavioralDailyRecord | None] = relationship(
        back_populates="risk_evaluations"
    )
    emotion_analysis_result: Mapped[EmotionAnalysisResult | None] = relationship(
        back_populates="risk_evaluations"
    )
    baseline: Mapped[BehavioralBaseline | None] = relationship(
        back_populates="risk_evaluations"
    )
    recovery_reports: Mapped[list[RecoveryReport]] = relationship(
        back_populates="risk_evaluation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RecoveryReport(Base):
    __tablename__ = "recovery_reports"
    __table_args__ = (
        CheckConstraint(
            "period_start <= period_end",
            name="ck_recovery_report_period",
        ),
        CheckConstraint(
            "generation_status IN ('llm_generated', 'template_fallback')",
            name="ck_recovery_report_generation_status",
        ),
        CheckConstraint(
            "length(trim(catalog_version)) > 0",
            name="ck_recovery_report_catalog_version_nonempty",
        ),
        CheckConstraint(
            "length(trim(prompt_version)) > 0",
            name="ck_recovery_report_prompt_version_nonempty",
        ),
        CheckConstraint(
            "model_name IS NULL OR length(trim(model_name)) > 0",
            name="ck_recovery_report_model_name_nonempty",
        ),
        Index(
            "ix_recovery_reports_user_generated_at",
            "user_id",
            "generated_at",
        ),
        Index(
            "ix_recovery_reports_risk_evaluation",
            "risk_evaluation_id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    risk_evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("burnout_risk_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(StrictJSON(), nullable=False)
    selected_actions: Mapped[list[dict[str, Any]]] = mapped_column(
        StrictJSON(),
        nullable=False,
    )
    content: Mapped[dict[str, Any]] = mapped_column(StrictJSON(), nullable=False)
    disclaimer: Mapped[str] = mapped_column(String(512), nullable=False)
    generation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128))
    generated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=_utc_now,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=_utc_now,
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="recovery_reports")
    risk_evaluation: Mapped[BurnoutRiskEvaluation] = relationship(
        back_populates="recovery_reports"
    )


__all__ = [
    "BehavioralBaseline",
    "BehavioralDailyRecord",
    "BurnoutRiskEvaluation",
    "DailyRecordSource",
    "EmotionAnalysisResult",
    "PersistenceBaselineStatus",
    "RecoveryReport",
]
