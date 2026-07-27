"""Align behavioral daily-record storage with the shared contract.

Revision ID: 20260727_0003
Revises: 20260725_0002
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260727_0003"
down_revision: str | None = "20260725_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgrade_is_lossless() -> None:
    if context.is_offline_mode():
        return

    lossy_or_incompatible_row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT id "
                "FROM behavioral_daily_records "
                "WHERE "
                "bedtime IS NOT NULL "
                "OR wake_time IS NOT NULL "
                "OR steps IS NOT NULL "
                "OR active_minutes IS NOT NULL "
                "OR source_by_field IS NOT NULL "
                "OR coverage_by_field IS NOT NULL "
                "OR (subjective_fatigue IS NOT NULL "
                "AND subjective_fatigue > 10) "
                "OR "
                "(schedule_count IS NOT NULL AND "
                "(CAST(schedule_count AS NUMERIC) < -2147483648 "
                "OR CAST(schedule_count AS NUMERIC) > 2147483647)) "
                "LIMIT 1"
            )
        )
        .first()
    )
    if lossy_or_incompatible_row is not None:
        raise RuntimeError(
            "Cannot downgrade 20260727_0003 to 20260725_0002: "
            "behavioral_daily_records contains 0003-only field data, "
            "subjective_fatigue above 10, or schedule_count outside the "
            "signed 32-bit integer range. Resolve or export those values "
            "explicitly before retrying; "
            "the downgrade did not modify them."
        )


def upgrade() -> None:
    with op.batch_alter_table("behavioral_daily_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "bedtime",
                sa.Time(timezone=False),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "wake_time",
                sa.Time(timezone=False),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("steps", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("active_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_by_field", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("coverage_by_field", sa.JSON(), nullable=True))
        batch_op.drop_constraint(
            "ck_daily_schedule_count",
            type_="check",
        )
        batch_op.alter_column(
            "schedule_count",
            existing_type=sa.Integer(),
            type_=sa.String(),
            existing_nullable=True,
            postgresql_using="schedule_count::text",
        )
        batch_op.create_check_constraint(
            "ck_daily_schedule_count",
            "schedule_count IS NULL OR "
            "CAST(schedule_count AS NUMERIC) >= 0",
        )
        batch_op.drop_constraint(
            "ck_daily_subjective_fatigue",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_daily_subjective_fatigue",
            "subjective_fatigue IS NULL OR subjective_fatigue >= 0",
        )
        batch_op.create_check_constraint(
            "ck_daily_steps",
            "steps IS NULL OR CAST(steps AS NUMERIC) >= 0",
        )
        batch_op.create_check_constraint(
            "ck_daily_active_minutes",
            "active_minutes IS NULL OR "
            "(active_minutes >= 0 AND active_minutes <= 1440)",
        )


def downgrade() -> None:
    _assert_downgrade_is_lossless()

    with op.batch_alter_table("behavioral_daily_records") as batch_op:
        batch_op.drop_constraint(
            "ck_daily_active_minutes",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_daily_steps",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_daily_subjective_fatigue",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_daily_schedule_count",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_daily_subjective_fatigue",
            "subjective_fatigue IS NULL OR "
            "(subjective_fatigue >= 0 AND subjective_fatigue <= 10)",
        )
        batch_op.alter_column(
            "schedule_count",
            existing_type=sa.String(),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using="schedule_count::integer",
        )
        batch_op.create_check_constraint(
            "ck_daily_schedule_count",
            "schedule_count IS NULL OR schedule_count >= 0",
        )
        batch_op.drop_column("coverage_by_field")
        batch_op.drop_column("source_by_field")
        batch_op.drop_column("active_minutes")
        batch_op.drop_column("steps")
        batch_op.drop_column("wake_time")
        batch_op.drop_column("bedtime")
