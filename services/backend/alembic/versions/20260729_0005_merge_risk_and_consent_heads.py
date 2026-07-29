"""merge risk evaluation and consent migration heads

Revision ID: 20260729_0005
Revises: 20260727_0004, f4c75e0aa428
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260729_0005"
down_revision: tuple[str, str] = ("20260727_0004", "f4c75e0aa428")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_risk_downgrade_is_lossless() -> None:
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
            "Cannot downgrade through 20260727_0004: "
            "behavioral_baselines contains subjective_fatigue above 10. "
            "Resolve or export those values explicitly before retrying; "
            "the downgrade did not modify them."
        )


def upgrade() -> None:
    """Join the two migration branches without changing storage."""


def downgrade() -> None:
    """Restore the two heads after verifying the risk branch is lossless."""

    _assert_risk_downgrade_is_lossless()
