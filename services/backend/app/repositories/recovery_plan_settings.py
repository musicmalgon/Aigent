from __future__ import annotations

from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.persistence import RecoveryPlanSettings


def get_recovery_plan_settings(
    session: Session,
    *,
    user_id: str,
) -> RecoveryPlanSettings | None:
    return session.scalar(
        select(RecoveryPlanSettings).where(
            RecoveryPlanSettings.user_id == user_id
        )
    )


def get_or_create_recovery_plan_settings(
    session: Session,
    *,
    user_id: str,
) -> RecoveryPlanSettings:
    """조회 전용 GET에서도 항상 행 하나를 돌려주기 위한 조회+생성.

    처음 조회하는 사용자는 전부 null(아직 아무것도 설정 안 함)인 기본
    행을 하나 만들어 둔다 -- 프론트가 "설정 없음"과 "조회 실패"를
    구분하지 않아도 되게 한다.
    """

    settings = get_recovery_plan_settings(session, user_id=user_id)
    if settings is not None:
        return settings

    settings = RecoveryPlanSettings(user_id=user_id)
    session.add(settings)
    session.flush()
    return settings


def update_recovery_plan_settings(
    settings: RecoveryPlanSettings,
    *,
    notification_time: time | None,
    notification_time_set: bool,
    target_period_start: date | None,
    target_period_end: date | None,
    target_period_set: bool,
) -> RecoveryPlanSettings:
    """PATCH 의미론 -- 값을 보낸 필드만 바꾼다.

    notification_time_set/target_period_set이 False면 그 필드는 요청에
    아예 없었다는 뜻이라 건드리지 않는다(None으로 보내서 지우는 것과
    다르다). 목표 기간은 시작/종료를 항상 한 쌍으로 다룬다 -- 하나만
    바뀌면 "시작일 > 종료일" 같은 중간 상태가 DB에 잠깐이라도 남을 수
    있기 때문이다.
    """

    if notification_time_set:
        settings.notification_time = notification_time
    if target_period_set:
        settings.target_period_start = target_period_start
        settings.target_period_end = target_period_end
    return settings


__all__ = [
    "get_or_create_recovery_plan_settings",
    "get_recovery_plan_settings",
    "update_recovery_plan_settings",
]
