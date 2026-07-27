"""Align risk-evaluation input storage and lookup indexes.

Revision ID: 20260727_0004
Revises: 20260727_0003
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260727_0004"
down_revision: str | None = "20260727_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgrade_is_lossless() -> None:
    if context.is_offline_mode():
        return

    incompatible_row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT id "
                "FROM behavioral_baselines "
                "WHERE subjective_fatigue IS NOT NULL "
                "AND subjective_fatigue > 10 "
                "LIMIT 1"
            )
        )
        .first()
    )
    if incompatible_row is not None:
        raise RuntimeError(
            "Cannot downgrade 20260727_0004 to 20260727_0003: "
            "behavioral_baselines contains subjective_fatigue above 10. "
            "Resolve or export those values explicitly before retrying; "
            "the downgrade did not modify them."
        )


def upgrade() -> None:
    with op.batch_alter_table("behavioral_baselines") as batch_op:
        batch_op.drop_constraint(
            "ck_baseline_subjective_fatigue",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_baseline_subjective_fatigue",
            "subjective_fatigue IS NULL OR subjective_fatigue >= 0",
        )

    op.create_index(
        "ix_emotion_results_user_record_date_analyzed_at",
        "emotion_analysis_results",
        ["user_id", "record_date", "analyzed_at"],
        unique=False,
    )
    op.create_index(
        "ix_behavioral_baselines_user_status_window_end",
        "behavioral_baselines",
        ["user_id", "status", "window_end"],
        unique=False,
    )


def downgrade() -> None:
    _assert_downgrade_is_lossless()

    op.drop_index(
        "ix_behavioral_baselines_user_status_window_end",
        table_name="behavioral_baselines",
    )
    op.drop_index(
        "ix_emotion_results_user_record_date_analyzed_at",
        table_name="emotion_analysis_results",
    )

    with op.batch_alter_table("behavioral_baselines") as batch_op:
        batch_op.drop_constraint(
            "ck_baseline_subjective_fatigue",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_baseline_subjective_fatigue",
            "subjective_fatigue IS NULL OR "
            "(subjective_fatigue >= 0 AND subjective_fatigue <= 10)",
        )
