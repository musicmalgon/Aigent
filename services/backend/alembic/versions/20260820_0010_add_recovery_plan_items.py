"""Add persisted user-selected recovery plan items."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0010"
down_revision: str | None = "20260820_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recovery_plan_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source_report_id", sa.String(), nullable=True),
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="planned",
            nullable=False,
        ),
        sa.Column(
            "selected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('planned', 'completed')",
            name="ck_recovery_plan_item_status",
        ),
        sa.CheckConstraint(
            "length(trim(action_id)) > 0",
            name="ck_recovery_plan_item_action_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_recovery_plan_item_title_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["source_report_id"],
            ["recovery_reports.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recovery_plan_items_user_status_selected_at",
        "recovery_plan_items",
        ["user_id", "status", "selected_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recovery_plan_items_user_status_selected_at",
        table_name="recovery_plan_items",
    )
    op.drop_table("recovery_plan_items")
