from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.domain.recovery.models import RecoveryActionId
from app.models.persistence import RecoveryPlanItem, RecoveryPlanSettings
from app.models.user import User
from app.repositories.recovery_plan_items import (
    create_recovery_plan_item,
    get_planned_action,
    get_recovery_plan_item,
    list_recovery_plan_items,
    update_recovery_plan_item_status,
)
from app.repositories.recovery_plan_settings import (
    get_or_create_recovery_plan_settings,
    update_recovery_plan_settings,
)
from app.repositories.recovery_reports import get_recovery_report
from app.schemas.recovery_plan import (
    RecoveryPlanItemCreate,
    RecoveryPlanItemResponse,
    RecoveryPlanItemUpdate,
    RecoveryPlanSettingsResponse,
    RecoveryPlanSettingsUpdate,
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


def _map_settings(settings: RecoveryPlanSettings) -> RecoveryPlanSettingsResponse:
    return RecoveryPlanSettingsResponse.model_validate(settings)


# "/settings"는 아래 "/{item_id}"보다 반드시 먼저 등록해야 한다 --
# 그렇지 않으면 GET/PATCH /settings 요청이 "/{item_id}"의 item_id="settings"로
# 먼저 매치되어 버린다(FastAPI/Starlette는 라우트를 등록 순서대로 매치한다).
@router.get("/settings", response_model=RecoveryPlanSettingsResponse)
def read_recovery_plan_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecoveryPlanSettingsResponse:
    try:
        settings = get_or_create_recovery_plan_settings(
            db,
            user_id=current_user.id,
        )
        response = _map_settings(settings)
        db.commit()
        return response
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Recovery plan settings could not be loaded.",
        ) from None


@router.patch("/settings", response_model=RecoveryPlanSettingsResponse)
def patch_recovery_plan_settings(
    payload: RecoveryPlanSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecoveryPlanSettingsResponse:
    try:
        settings = get_or_create_recovery_plan_settings(
            db,
            user_id=current_user.id,
        )
        fields_set = payload.model_fields_set
        update_recovery_plan_settings(
            settings,
            notification_time=payload.notification_time,
            notification_time_set="notification_time" in fields_set,
            target_period_start=payload.target_period_start,
            target_period_end=payload.target_period_end,
            target_period_set="target_period_start" in fields_set,
        )
        response = _map_settings(settings)
        db.commit()
        return response
    except (SQLAlchemyError, ValidationError, ValueError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Recovery plan settings could not be saved.",
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
