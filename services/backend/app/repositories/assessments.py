from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete, update
from sqlalchemy.orm import Session

from app.models.assessment import AssessmentAnchor


def delete_all_assessment_anchors_for_user(
    session: Session,
    *,
    user_id: str,
) -> int:
    # supersedes_id가 같은 테이블(assessment_anchors)을 자기참조하는 FK라서,
    # 참조 대상 행이 참조하는 행보다 먼저 지워지면 FK 제약(SQLite도
    # PRAGMA foreign_keys=ON으로 켜져 있음)에 걸릴 수 있다. 한 사용자의
    # 행끼리만 서로 참조하므로, 전부 지우기 전에 참조를 먼저 끊어준다.
    session.execute(
        update(AssessmentAnchor)
        .where(AssessmentAnchor.user_id == user_id)
        .values(supersedes_id=None)
    )
    result = cast(
        "CursorResult[Any]",
        session.execute(
            delete(AssessmentAnchor).where(AssessmentAnchor.user_id == user_id)
        ),
    )
    session.flush()
    return result.rowcount


__all__ = ["delete_all_assessment_anchors_for_user"]
