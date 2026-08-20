"""Add per-user recovery plan settings (notification time, target period)."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0011"
down_revision: str | None = "20260820_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recovery_plan_settings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("notification_time", sa.Time(), nullable=True),
        sa.Column("target_period_start", sa.Date(), nullable=True),
        sa.Column("target_period_end", sa.Date(), nullable=True),
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
            "target_period_start IS NULL OR target_period_end IS NULL OR "
            "target_period_start <= target_period_end",
            name="ck_recovery_plan_settings_period_order",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recovery_plan_settings_user_id",
        "recovery_plan_settings",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recovery_plan_settings_user_id",
        table_name="recovery_plan_settings",
    )
    op.drop_table("recovery_plan_settings")
