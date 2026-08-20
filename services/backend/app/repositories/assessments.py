from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.orm import Session

from app.models.assessment import AssessmentAnchor, AssessmentType


def get_latest_assessment_anchor(
    session: Session,
    *,
    user_id: str,
    assessment_type: AssessmentType,
    source: str | None = None,
) -> AssessmentAnchor | None:
    """가장 최근에 완료한(자가보고 완료 시각 기준) 검사 앵커를 찾는다.

    source를 주면 그 값과 정확히 같은 것만 본다 -- 같은 assessment_type 안에
    채점 방식이 바뀐(source 버전이 바뀐) 과거 기록을 새 로직에 잘못
    섞어 넣지 않기 위함이다.
    """
    statement = select(AssessmentAnchor).where(
        AssessmentAnchor.user_id == user_id,
        AssessmentAnchor.assessment_type == assessment_type,
    )
    if source is not None:
        statement = statement.where(AssessmentAnchor.source == source)
    statement = statement.order_by(
        AssessmentAnchor.completed_at.desc(),
        AssessmentAnchor.created_at.desc(),
    )
    return session.scalar(statement)


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


__all__ = [
    "delete_all_assessment_anchors_for_user",
    "get_latest_assessment_anchor",
]
