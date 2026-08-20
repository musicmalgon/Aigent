from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.domain.recovery.models import RecoveryActionId
from app.models.persistence import RecoveryPlanItem
from app.models.user import User
from app.repositories.recovery_plan_items import (
    create_recovery_plan_item,
    get_planned_action,
    get_recovery_plan_item,
    list_recovery_plan_items,
    update_recovery_plan_item_status,
)
from app.repositories.recovery_reports import get_recovery_report
from app.schemas.recovery_plan import (
    RecoveryPlanItemCreate,
    RecoveryPlanItemResponse,
    RecoveryPlanItemUpdate,
)

router = APIRouter(
    prefix="/api/v1/recovery-plans",
    tags=["recovery-plans"],
)


def _map(item: RecoveryPlanItem) -> RecoveryPlanItemResponse:
    return RecoveryPlanItemResponse.model_validate(item)


@router.get("", response_model=list[RecoveryPlanItemResponse])
def read_recovery_plan(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RecoveryPlanItemResponse]:
    return [
        _map(item)
        for item in list_recovery_plan_items(db, user_id=current_user.id)
    ]


@router.post("", response_model=RecoveryPlanItemResponse, status_code=201)
def add_recovery_plan_item(
    payload: RecoveryPlanItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecoveryPlanItemResponse:
    try:
        action_id = RecoveryActionId(payload.action_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unknown recovery action.",
        ) from None
    if get_planned_action(db, user_id=current_user.id, action_id=action_id.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery action is already in the plan.",
        )
    if payload.source_report_id is not None:
        report = get_recovery_report(
            db,
            user_id=current_user.id,
            report_id=payload.source_report_id,
        )
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recovery report not found.",
            )
    try:
        item = create_recovery_plan_item(
            db,
            user_id=current_user.id,
            action_id=action_id,
            source_report_id=payload.source_report_id,
        )
        response = _map(item)
        db.commit()
        return response
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Recovery plan item could not be saved.",
        ) from None


@router.patch("/{item_id}", response_model=RecoveryPlanItemResponse)
def update_recovery_plan_item(
    item_id: str,
    payload: RecoveryPlanItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecoveryPlanItemResponse:
    item = get_recovery_plan_item(
        db,
        user_id=current_user.id,
        item_id=item_id,
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recovery plan item not found.",
        )
    try:
        update_recovery_plan_item_status(item, status=payload.status)
        response = _map(item)
        db.commit()
        return response
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Recovery plan item could not be updated.",
        ) from None


__all__ = ["router"]
