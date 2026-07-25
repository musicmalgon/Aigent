from __future__ import annotations

from sqlalchemy import select
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
) -> BehavioralBaseline | None:
    return session.scalar(
        select(BehavioralBaseline).where(
            BehavioralBaseline.id == baseline_id,
            BehavioralBaseline.user_id == user_id,
        )
    )


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
) -> list[BehavioralBaseline]:
    return list(
        session.scalars(
            select(BehavioralBaseline)
            .where(BehavioralBaseline.user_id == user_id)
            .order_by(
                BehavioralBaseline.window_end.desc(),
                BehavioralBaseline.created_at.desc(),
            )
        )
    )


__all__ = [
    "create_baseline",
    "get_baseline",
    "get_latest_ready_baseline",
    "list_baselines",
]
