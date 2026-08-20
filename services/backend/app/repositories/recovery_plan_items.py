from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.orm import Session

from app.domain.recovery.catalog import get_recovery_action
from app.domain.recovery.models import RecoveryActionId
from app.models.persistence import RecoveryPlanItem


def list_recovery_plan_items(
    session: Session,
    *,
    user_id: str,
) -> list[RecoveryPlanItem]:
    return list(
        session.scalars(
            select(RecoveryPlanItem)
            .where(RecoveryPlanItem.user_id == user_id)
            .order_by(
                RecoveryPlanItem.status.asc(),
                RecoveryPlanItem.selected_at.desc(),
                RecoveryPlanItem.id.desc(),
            )
        )
    )


def get_recovery_plan_item(
    session: Session,
    *,
    user_id: str,
    item_id: str,
) -> RecoveryPlanItem | None:
    return session.scalar(
        select(RecoveryPlanItem).where(
            RecoveryPlanItem.id == item_id,
            RecoveryPlanItem.user_id == user_id,
        )
    )


def get_planned_action(
    session: Session,
    *,
    user_id: str,
    action_id: str,
) -> RecoveryPlanItem | None:
    return session.scalar(
        select(RecoveryPlanItem).where(
            RecoveryPlanItem.user_id == user_id,
            RecoveryPlanItem.action_id == action_id,
            RecoveryPlanItem.status == "planned",
        )
    )


def create_recovery_plan_item(
    session: Session,
    *,
    user_id: str,
    action_id: RecoveryActionId,
    source_report_id: str | None,
) -> RecoveryPlanItem:
    action = get_recovery_action(action_id)
    item = RecoveryPlanItem(
        user_id=user_id,
        source_report_id=source_report_id,
        action_id=action.id.value,
        title=action.title,
        duration_minutes=action.duration_minutes,
        difficulty=action.difficulty.value,
    )
    session.add(item)
    session.flush()
    return item


def update_recovery_plan_item_status(
    item: RecoveryPlanItem,
    *,
    status: str,
) -> RecoveryPlanItem:
    item.status = status
    item.completed_at = datetime.now(UTC) if status == "completed" else None
    return item


def delete_all_recovery_plan_items_for_user(
    session: Session,
    *,
    user_id: str,
) -> int:
    result = cast(
        "CursorResult[Any]",
        session.execute(
            delete(RecoveryPlanItem).where(RecoveryPlanItem.user_id == user_id)
        ),
    )
    session.flush()
    return result.rowcount


__all__ = [
    "create_recovery_plan_item",
    "delete_all_recovery_plan_items_for_user",
    "get_planned_action",
    "get_recovery_plan_item",
    "list_recovery_plan_items",
    "update_recovery_plan_item_status",
]
