"""Add Emotion Taxonomy v2 provenance storage.

Revision ID: 20260729_0006
Revises: 20260729_0005
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260729_0006"
down_revision: str | None = "20260729_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_V1_LABELS = "('기쁨', '불안', '당황', '분노', '슬픔', '상처')"
_V2_LABELS = "('분노', '기쁨', '불안', '당황', '슬픔', '무기력')"


def _taxonomy_payload_check() -> str:
    return (
        "("
        "taxonomy_version = 'v1' "
        f"AND predicted_emotion IN {_V1_LABELS} "
        "AND emotion = predicted_emotion "
        "AND provisional = 0 "
        "AND margin IS NULL "
        "AND threshold_version IS NULL"
        ") OR ("
        "taxonomy_version = 'v2' "
        f"AND predicted_emotion IN {_V2_LABELS} "
        "AND margin IS NOT NULL "
        "AND threshold_version IS NOT NULL "
        "AND length(trim(threshold_version)) > 0 "
        "AND provisional = is_uncertain "
        "AND ("
        "(provisional = 1 AND emotion IS NULL) "
        "OR (provisional = 0 AND emotion = predicted_emotion)"
        ")"
        ")"
    )


def _assert_downgrade_is_lossless() -> None:
    if context.is_offline_mode():
        return

    incompatible_row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT id "
                "FROM emotion_analysis_results "
                "WHERE taxonomy_version <> 'v1' "
                "OR emotion IS NULL "
                "OR emotion <> predicted_emotion "
                "OR provisional <> 0 "
                "OR margin IS NOT NULL "
                "OR threshold_version IS NOT NULL "
                "LIMIT 1"
            )
        )
        .first()
    )
    if incompatible_row is not None:
        raise RuntimeError(
            "Cannot downgrade 20260729_0006: emotion_analysis_results "
            "contains Emotion Taxonomy v2 or non-legacy provenance. "
            "Export or remove those append-only rows explicitly before retrying; "
            "the downgrade did not modify them."
        )


def upgrade() -> None:
    with op.batch_alter_table("emotion_analysis_results") as batch_op:
        batch_op.add_column(
            sa.Column(
                "taxonomy_version",
                sa.String(length=16),
                server_default="v1",
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("emotion", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(sa.Column("margin", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "provisional",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("threshold_version", sa.String(length=64), nullable=True)
        )

    op.execute(
        sa.text(
            "UPDATE emotion_analysis_results "
            "SET taxonomy_version = 'v1', "
            "emotion = predicted_emotion, "
            "provisional = 0"
        )
    )

    with op.batch_alter_table("emotion_analysis_results") as batch_op:
        batch_op.alter_column(
            "taxonomy_version",
            existing_type=sa.String(length=16),
            nullable=False,
            server_default="v1",
        )
        batch_op.alter_column(
            "provisional",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        )
        batch_op.drop_constraint(
            "ck_emotion_predicted_label",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_emotion_taxonomy_payload",
            _taxonomy_payload_check(),
        )
        batch_op.create_check_constraint(
            "ck_emotion_margin",
            "margin IS NULL OR (margin >= 0 AND margin <= 1)",
        )


def downgrade() -> None:
    _assert_downgrade_is_lossless()

    with op.batch_alter_table("emotion_analysis_results") as batch_op:
        batch_op.drop_constraint(
            "ck_emotion_margin",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_emotion_taxonomy_payload",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_emotion_predicted_label",
            f"predicted_emotion IN {_V1_LABELS}",
        )
        batch_op.drop_column("threshold_version")
        batch_op.drop_column("provisional")
        batch_op.drop_column("margin")
        batch_op.drop_column("emotion")
        batch_op.drop_column("taxonomy_version")
