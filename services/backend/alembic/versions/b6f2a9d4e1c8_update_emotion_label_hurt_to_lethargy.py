"""Update emotion label taxonomy: 무기력 -> 무기력.

Revision ID: b6f2a9d4e1c8
Revises: 20260729_0005
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6f2a9d4e1c8"
down_revision: str | None = "20260729_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_LABEL = "무기력"
NEW_LABEL = "무기력"

EMOTION_RESULTS = sa.table(
    "emotion_analysis_results",
    sa.column("id", sa.String()),
    sa.column("predicted_emotion", sa.String()),
    sa.column("probabilities", sa.JSON()),
)


def _migrate_rows(*, old_label: str, new_label: str) -> None:
    context = op.get_context()
    if context.as_sql:
        # Offline SQL 렌더링(--sql) 모드에는 라이브 DB 연결이 없어서
        # 행 단위 데이터 이전을 건너뜁니다. 실제 upgrade 실행 시에만 동작합니다.
        return

    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            EMOTION_RESULTS.c.id,
            EMOTION_RESULTS.c.predicted_emotion,
            EMOTION_RESULTS.c.probabilities,
        )
    ).fetchall()

    for row in rows:
        probabilities = dict(row.probabilities or {})
        changed = False

        if old_label in probabilities:
            probabilities[new_label] = probabilities.pop(old_label)
            changed = True

        new_predicted = row.predicted_emotion
        if new_predicted == old_label:
            new_predicted = new_label
            changed = True

        if changed:
            bind.execute(
                EMOTION_RESULTS.update()
                .where(EMOTION_RESULTS.c.id == row.id)
                .values(
                    predicted_emotion=new_predicted,
                    probabilities=probabilities,
                )
            )


def upgrade() -> None:
    _migrate_rows(old_label=OLD_LABEL, new_label=NEW_LABEL)

    with op.batch_alter_table(
        "emotion_analysis_results", schema=None
    ) as batch_op:
        batch_op.drop_constraint("ck_emotion_predicted_label", type_="check")
        batch_op.create_check_constraint(
            "ck_emotion_predicted_label",
            "predicted_emotion IN "
            "('기쁨', '불안', '당황', '분노', '슬픔', '무기력')",
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "emotion_analysis_results", schema=None
    ) as batch_op:
        batch_op.drop_constraint("ck_emotion_predicted_label", type_="check")
        batch_op.create_check_constraint(
            "ck_emotion_predicted_label",
            "predicted_emotion IN "
            "('기쁨', '불안', '당황', '분노', '슬픔', '무기력')",
        )

    _migrate_rows(old_label=NEW_LABEL, new_label=OLD_LABEL)