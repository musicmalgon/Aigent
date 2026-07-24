"""Add behavioral and burnout-risk persistence tables.

Revision ID: 20260725_0002
Revises: 20260725_0001
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260725_0002"
down_revision: str | None = "20260725_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "behavioral_daily_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("sleep_minutes", sa.Integer(), nullable=True),
        sa.Column("study_work_minutes", sa.Integer(), nullable=True),
        sa.Column("rest_minutes", sa.Integer(), nullable=True),
        sa.Column("exercise_minutes", sa.Integer(), nullable=True),
        sa.Column("schedule_count", sa.Integer(), nullable=True),
        sa.Column("subjective_stress", sa.Float(), nullable=True),
        sa.Column("subjective_fatigue", sa.Float(), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "calendar",
                "health_connect",
                "imported",
                name="daily_record_source",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="manual",
            nullable=False,
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="UTC",
            nullable=False,
        ),
        sa.Column("data_completeness", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "data_completeness IS NULL OR "
            "(data_completeness >= 0 AND data_completeness <= 1)",
            name="ck_daily_data_completeness",
        ),
        sa.CheckConstraint(
            "length(trim(timezone)) > 0",
            name="ck_daily_timezone_nonempty",
        ),
        sa.CheckConstraint(
            "exercise_minutes IS NULL OR "
            "(exercise_minutes >= 0 AND exercise_minutes <= 1440)",
            name="ck_daily_exercise_minutes",
        ),
        sa.CheckConstraint(
            "rest_minutes IS NULL OR "
            "(rest_minutes >= 0 AND rest_minutes <= 1440)",
            name="ck_daily_rest_minutes",
        ),
        sa.CheckConstraint(
            "schedule_count IS NULL OR schedule_count >= 0",
            name="ck_daily_schedule_count",
        ),
        sa.CheckConstraint(
            "sleep_minutes IS NULL OR "
            "(sleep_minutes >= 0 AND sleep_minutes <= 1440)",
            name="ck_daily_sleep_minutes",
        ),
        sa.CheckConstraint(
            "study_work_minutes IS NULL OR "
            "(study_work_minutes >= 0 AND study_work_minutes <= 1440)",
            name="ck_daily_study_work_minutes",
        ),
        sa.CheckConstraint(
            "subjective_fatigue IS NULL OR "
            "(subjective_fatigue >= 0 AND subjective_fatigue <= 10)",
            name="ck_daily_subjective_fatigue",
        ),
        sa.CheckConstraint(
            "subjective_stress IS NULL OR "
            "(subjective_stress >= 0 AND subjective_stress <= 10)",
            name="ck_daily_subjective_stress",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_daily_records_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "record_date",
            name="uq_behavioral_daily_records_user_date",
        ),
    )

    op.create_table(
        "emotion_analysis_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("predicted_emotion", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_uncertain", sa.Boolean(), nullable=False),
        sa.Column("probabilities", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_emotion_confidence",
        ),
        sa.CheckConstraint(
            "input_hash IS NULL OR length(trim(input_hash)) > 0",
            name="ck_emotion_input_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(model_version)) > 0",
            name="ck_emotion_model_version_nonempty",
        ),
        sa.CheckConstraint(
            "predicted_emotion IN "
            "('기쁨', '불안', '당황', '분노', '슬픔', '상처')",
            name="ck_emotion_predicted_label",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_emotion_results_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_emotion_results_user_analyzed_at",
        "emotion_analysis_results",
        ["user_id", "analyzed_at"],
        unique=False,
    )

    op.create_table(
        "behavioral_baselines",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("sample_days", sa.Integer(), nullable=False),
        sa.Column("sleep_minutes", sa.Float(), nullable=True),
        sa.Column("study_work_minutes", sa.Float(), nullable=True),
        sa.Column("rest_minutes", sa.Float(), nullable=True),
        sa.Column("exercise_minutes", sa.Float(), nullable=True),
        sa.Column("schedule_count", sa.Float(), nullable=True),
        sa.Column("subjective_stress", sa.Float(), nullable=True),
        sa.Column("subjective_fatigue", sa.Float(), nullable=True),
        sa.Column(
            "negative_emotion_probability",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "ready",
                "insufficient",
                name="persistence_baseline_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "algorithm_version",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "exercise_minutes IS NULL OR "
            "(exercise_minutes >= 0 AND exercise_minutes <= 1440)",
            name="ck_baseline_exercise_minutes",
        ),
        sa.CheckConstraint(
            "length(trim(algorithm_version)) > 0",
            name="ck_baseline_algorithm_version_nonempty",
        ),
        sa.CheckConstraint(
            "negative_emotion_probability IS NULL OR "
            "(negative_emotion_probability >= 0 "
            "AND negative_emotion_probability <= 1)",
            name="ck_baseline_negative_emotion_probability",
        ),
        sa.CheckConstraint(
            "rest_minutes IS NULL OR "
            "(rest_minutes >= 0 AND rest_minutes <= 1440)",
            name="ck_baseline_rest_minutes",
        ),
        sa.CheckConstraint(
            "sample_days >= 0",
            name="ck_baseline_sample_days",
        ),
        sa.CheckConstraint(
            "schedule_count IS NULL OR schedule_count >= 0",
            name="ck_baseline_schedule_count",
        ),
        sa.CheckConstraint(
            "sleep_minutes IS NULL OR "
            "(sleep_minutes >= 0 AND sleep_minutes <= 1440)",
            name="ck_baseline_sleep_minutes",
        ),
        sa.CheckConstraint(
            "study_work_minutes IS NULL OR "
            "(study_work_minutes >= 0 AND study_work_minutes <= 1440)",
            name="ck_baseline_study_work_minutes",
        ),
        sa.CheckConstraint(
            "subjective_fatigue IS NULL OR "
            "(subjective_fatigue >= 0 AND subjective_fatigue <= 10)",
            name="ck_baseline_subjective_fatigue",
        ),
        sa.CheckConstraint(
            "subjective_stress IS NULL OR "
            "(subjective_stress >= 0 AND subjective_stress <= 10)",
            name="ck_baseline_subjective_stress",
        ),
        sa.CheckConstraint(
            "window_start <= window_end",
            name="ck_baseline_window_order",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_behavioral_baselines_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_behavioral_baselines_user_window_end",
        "behavioral_baselines",
        ["user_id", "window_end"],
        unique=False,
    )

    op.create_table(
        "burnout_risk_evaluations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("daily_record_id", sa.String(), nullable=True),
        sa.Column(
            "emotion_analysis_result_id",
            sa.String(),
            nullable=True,
        ),
        sa.Column("baseline_id", sa.String(), nullable=True),
        sa.Column("engine_version", sa.String(length=128), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("is_provisional", sa.Boolean(), nullable=False),
        sa.Column("baseline_status", sa.String(length=32), nullable=False),
        sa.Column("data_quality", sa.String(length=32), nullable=False),
        sa.Column("category_scores", sa.JSON(), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "baseline_status IN ('ready', 'insufficient', 'missing')",
            name="ck_risk_evaluation_baseline_status",
        ),
        sa.CheckConstraint(
            "data_quality IN ('sufficient', 'insufficient')",
            name="ck_risk_evaluation_data_quality",
        ),
        sa.CheckConstraint(
            "level IN ('low', 'moderate', 'high', 'very_high')",
            name="ck_risk_evaluation_level",
        ),
        sa.CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_risk_evaluation_engine_version_nonempty",
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100",
            name="ck_risk_evaluation_score",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_id"],
            ["behavioral_baselines.id"],
            name="fk_risk_evaluations_baseline_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["daily_record_id"],
            ["behavioral_daily_records.id"],
            name="fk_risk_evaluations_daily_record_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["emotion_analysis_result_id"],
            ["emotion_analysis_results.id"],
            name="fk_risk_evaluations_emotion_result_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_risk_evaluations_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_risk_evaluations_user_evaluated_at",
        "burnout_risk_evaluations",
        ["user_id", "evaluated_at"],
        unique=False,
    )
    op.create_index(
        "ix_risk_evaluations_user_record_date",
        "burnout_risk_evaluations",
        ["user_id", "record_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_risk_evaluations_user_record_date",
        table_name="burnout_risk_evaluations",
    )
    op.drop_index(
        "ix_risk_evaluations_user_evaluated_at",
        table_name="burnout_risk_evaluations",
    )
    op.drop_table("burnout_risk_evaluations")

    op.drop_index(
        "ix_behavioral_baselines_user_window_end",
        table_name="behavioral_baselines",
    )
    op.drop_table("behavioral_baselines")

    op.drop_index(
        "ix_emotion_results_user_analyzed_at",
        table_name="emotion_analysis_results",
    )
    op.drop_table("emotion_analysis_results")

    op.drop_table("behavioral_daily_records")
