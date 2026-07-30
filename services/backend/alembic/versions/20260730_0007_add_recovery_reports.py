"""Add deterministic recovery reports and generation provenance.

Revision ID: 20260730_0007
Revises: 20260729_0006
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260730_0007"
down_revision: str | None = "20260729_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgrade_is_lossless() -> None:
    if context.is_offline_mode():
        return
    existing = op.get_bind().execute(
        sa.text("SELECT id FROM recovery_reports LIMIT 1")
    ).first()
    if existing is not None:
        raise RuntimeError(
            "Cannot downgrade 20260730_0007: recovery_reports contains "
            "generated report history. Export or remove those rows explicitly "
            "before retrying; the downgrade did not modify them."
        )


def upgrade() -> None:
    op.create_table(
        "recovery_reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("risk_evaluation_id", sa.String(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("selected_actions", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("disclaimer", sa.String(length=512), nullable=False),
        sa.Column("generation_status", sa.String(length=32), nullable=False),
        sa.Column("catalog_version", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "period_start <= period_end",
            name="ck_recovery_report_period",
        ),
        sa.CheckConstraint(
            "generation_status IN ('llm_generated', 'template_fallback')",
            name="ck_recovery_report_generation_status",
        ),
        sa.CheckConstraint(
            "length(trim(catalog_version)) > 0",
            name="ck_recovery_report_catalog_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(prompt_version)) > 0",
            name="ck_recovery_report_prompt_version_nonempty",
        ),
        sa.CheckConstraint(
            "model_name IS NULL OR length(trim(model_name)) > 0",
            name="ck_recovery_report_model_name_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["risk_evaluation_id"],
            ["burnout_risk_evaluations.id"],
            name="fk_recovery_reports_risk_evaluation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_recovery_reports_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recovery_reports_user_generated_at",
        "recovery_reports",
        ["user_id", "generated_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_reports_risk_evaluation",
        "recovery_reports",
        ["risk_evaluation_id"],
        unique=False,
    )


def downgrade() -> None:
    _assert_downgrade_is_lossless()
    op.drop_index(
        "ix_recovery_reports_risk_evaluation",
        table_name="recovery_reports",
    )
    op.drop_index(
        "ix_recovery_reports_user_generated_at",
        table_name="recovery_reports",
    )
    op.drop_table("recovery_reports")
