from __future__ import annotations

from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.orm import Session

from app.models.persistence import (
    BehavioralBaseline,
    PersistenceBaselineStatus,
)


def create_baseline(
    session: Session,
    baseline: BehavioralBaseline,
) -> BehavioralBaseline:
    session.add(baseline)
    session.flush()
    return baseline


def get_baseline(
    session: Session,
    *,
    user_id: str,
    baseline_id: str,
    for_update: bool = False,
) -> BehavioralBaseline | None:
    statement = select(BehavioralBaseline).where(
        BehavioralBaseline.id == baseline_id,
        BehavioralBaseline.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def get_latest_ready_baseline(
    session: Session,
    *,
    user_id: str,
) -> BehavioralBaseline | None:
    return session.scalar(
        select(BehavioralBaseline)
        .where(
            BehavioralBaseline.user_id == user_id,
            BehavioralBaseline.status == PersistenceBaselineStatus.READY,
        )
        .order_by(
            BehavioralBaseline.created_at.desc(),
            BehavioralBaseline.id.desc(),
        )
        .limit(1)
    )


def get_latest_ready_baseline_before(
    session: Session,
    *,
    user_id: str,
    evaluation_date: date,
    minimum_sample_days: int = 7,
) -> BehavioralBaseline | None:
    return session.scalar(
        select(BehavioralBaseline)
        .where(
            BehavioralBaseline.user_id == user_id,
            BehavioralBaseline.status == PersistenceBaselineStatus.READY,
            BehavioralBaseline.sample_days >= minimum_sample_days,
            BehavioralBaseline.window_end < evaluation_date,
        )
        .order_by(
            BehavioralBaseline.window_end.desc(),
            BehavioralBaseline.created_at.desc(),
            BehavioralBaseline.id.desc(),
        )
        .limit(1)
    )


def list_baselines(
    session: Session,
    *,
    user_id: str,
    status: PersistenceBaselineStatus | None = None,
    window_end_from: date | None = None,
    window_end_to: date | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[BehavioralBaseline]:
    statement = select(BehavioralBaseline).where(BehavioralBaseline.user_id == user_id)
    if status is not None:
        statement = statement.where(BehavioralBaseline.status == status)
    if window_end_from is not None:
        statement = statement.where(BehavioralBaseline.window_end >= window_end_from)
    if window_end_to is not None:
        statement = statement.where(BehavioralBaseline.window_end <= window_end_to)
    statement = statement.order_by(
        BehavioralBaseline.created_at.desc(),
        BehavioralBaseline.id.desc(),
    )
    if offset:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.scalars(statement))


def delete_all_baselines_for_user(
    session: Session,
    *,
    user_id: str,
) -> int:
    # Session.execute의 정적 반환 타입은 Result지만 DML은 CursorResult를 준다.
    result = cast(
        "CursorResult[Any]",
        session.execute(
            delete(BehavioralBaseline).where(
                BehavioralBaseline.user_id == user_id
            )
        ),
    )
    session.flush()
    return result.rowcount


__all__ = [
    "create_baseline",
    "delete_all_baselines_for_user",
    "get_baseline",
    "get_latest_ready_baseline",
    "get_latest_ready_baseline_before",
    "list_baselines",
]
