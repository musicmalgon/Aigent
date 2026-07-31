"""Add neutral-gate provenance to emotion analysis results.

Revision ID: 20260731_0008
Revises: 20260730_0007
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260731_0008"
down_revision: str | None = "20260730_0007"
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
        "AND provisional = FALSE "
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
        "AND provisional = TRUE "
        "AND is_uncertain = TRUE"
        ") OR ("
        f"predicted_emotion IN {_V2_LABELS} "
        "AND confidence IS NOT NULL "
        "AND margin IS NOT NULL "
        "AND probabilities IS NOT NULL "
        "AND provisional = is_uncertain "
        "AND ("
        "(provisional = TRUE AND emotion IS NULL) "
        "OR (provisional = FALSE AND emotion = predicted_emotion)"
        ")"
        ")"
        ")"
        ")"
    )


def _legacy_taxonomy_payload_check() -> str:
    return (
        "("
        "taxonomy_version = 'v1' "
        f"AND predicted_emotion IN {_V1_LABELS} "
        "AND emotion = predicted_emotion "
        "AND provisional = FALSE "
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
        "(provisional = TRUE AND emotion IS NULL) "
        "OR (provisional = FALSE AND emotion = predicted_emotion)"
        ")"
        ")"
    )


def _gate_provenance_check() -> str:
    return (
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
        ")"
    )


def _assert_downgrade_is_lossless() -> None:
    if context.is_offline_mode():
        return
    incompatible = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT id FROM emotion_analysis_results "
                "WHERE neutral_gate_decision IS NOT NULL "
                "OR neutral_gate_score IS NOT NULL "
                "OR neutral_gate_model_version IS NOT NULL "
                "OR neutral_gate_threshold IS NOT NULL "
                "OR predicted_emotion IS NULL "
                "OR confidence IS NULL "
                "OR probabilities IS NULL "
                "LIMIT 1"
            )
        )
        .first()
    )
    if incompatible is not None:
        raise RuntimeError(
            "Cannot downgrade 20260731_0008: emotion_analysis_results contains "
            "neutral-gate provenance or neutral decisions. Export or remove those "
            "append-only rows explicitly before retrying; the downgrade did not "
            "modify them."
        )


def upgrade() -> None:
    with op.batch_alter_table("emotion_analysis_results") as batch_op:
        batch_op.drop_constraint("ck_emotion_confidence", type_="check")
        batch_op.drop_constraint("ck_emotion_taxonomy_payload", type_="check")
        batch_op.add_column(
            sa.Column("neutral_gate_decision", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(sa.Column("neutral_gate_score", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "neutral_gate_model_version",
                sa.String(length=128),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("neutral_gate_threshold", sa.Float(), nullable=True)
        )
        batch_op.alter_column(
            "predicted_emotion",
            existing_type=sa.String(length=16),
            nullable=True,
        )
        batch_op.alter_column(
            "confidence",
            existing_type=sa.Float(),
            nullable=True,
        )
        batch_op.alter_column(
            "probabilities",
            existing_type=sa.JSON(none_as_null=True),
            nullable=True,
        )
        batch_op.create_check_constraint(
            "ck_emotion_confidence",
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
        )
        batch_op.create_check_constraint(
            "ck_emotion_taxonomy_payload",
            _taxonomy_payload_check(),
        )
        batch_op.create_check_constraint(
            "ck_emotion_neutral_gate_provenance",
            _gate_provenance_check(),
        )


def downgrade() -> None:
    _assert_downgrade_is_lossless()
    with op.batch_alter_table("emotion_analysis_results") as batch_op:
        batch_op.drop_constraint(
            "ck_emotion_neutral_gate_provenance",
            type_="check",
        )
        batch_op.drop_constraint("ck_emotion_taxonomy_payload", type_="check")
        batch_op.drop_constraint("ck_emotion_confidence", type_="check")
        batch_op.alter_column(
            "probabilities",
            existing_type=sa.JSON(none_as_null=True),
            nullable=False,
        )
        batch_op.alter_column(
            "confidence",
            existing_type=sa.Float(),
            nullable=False,
        )
        batch_op.alter_column(
            "predicted_emotion",
            existing_type=sa.String(length=16),
            nullable=False,
        )
        batch_op.drop_column("neutral_gate_threshold")
        batch_op.drop_column("neutral_gate_model_version")
        batch_op.drop_column("neutral_gate_score")
        batch_op.drop_column("neutral_gate_decision")
        batch_op.create_check_constraint(
            "ck_emotion_confidence",
            "confidence >= 0 AND confidence <= 1",
        )
        batch_op.create_check_constraint(
            "ck_emotion_taxonomy_payload",
            _legacy_taxonomy_payload_check(),
        )
