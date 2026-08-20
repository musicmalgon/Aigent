"""Store informational Stage 2 signals with emotion analyses."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0009"
down_revision: str | None = "50390f608ff5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "emotion_analysis_results",
        sa.Column("burnout_signal_payload", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("emotion_analysis_results", "burnout_signal_payload")
