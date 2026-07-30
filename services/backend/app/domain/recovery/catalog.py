from __future__ import annotations

from types import MappingProxyType

from .models import (
    RecoveryAction,
    RecoveryActionId,
    RecoveryDifficulty,
    ReportFactorCode,
)

CATALOG_VERSION = "recovery-catalog-v1"

_ACTIONS = MappingProxyType(
    {
        RecoveryActionId.REST_30: RecoveryAction(
            id=RecoveryActionId.REST_30,
            title="방해받지 않는 휴식 30분",
            duration_minutes=30,
            difficulty=RecoveryDifficulty.EASY,
        ),
        RecoveryActionId.SLEEP_EARLY_60: RecoveryAction(
            id=RecoveryActionId.SLEEP_EARLY_60,
            title="잠드는 시간을 조금 앞당기기",
            duration_minutes=60,
            difficulty=RecoveryDifficulty.MEDIUM,
        ),
        RecoveryActionId.LIGHT_ACTIVITY_20: RecoveryAction(
            id=RecoveryActionId.LIGHT_ACTIVITY_20,
            title="가벼운 움직임 20분",
            duration_minutes=20,
            difficulty=RecoveryDifficulty.EASY,
        ),
        RecoveryActionId.SCHEDULE_REDUCE_ONE: RecoveryAction(
            id=RecoveryActionId.SCHEDULE_REDUCE_ONE,
            title="오늘 일정 한 가지 덜어내기",
            duration_minutes=None,
            difficulty=RecoveryDifficulty.MEDIUM,
        ),
        RecoveryActionId.JOURNAL_CHECKIN_10: RecoveryAction(
            id=RecoveryActionId.JOURNAL_CHECKIN_10,
            title="지금 감정을 10분간 적어보기",
            duration_minutes=10,
            difficulty=RecoveryDifficulty.EASY,
        ),
        RecoveryActionId.ROUTINE_CHECK_5: RecoveryAction(
            id=RecoveryActionId.ROUTINE_CHECK_5,
            title="오늘의 생활 리듬 5분 점검",
            duration_minutes=5,
            difficulty=RecoveryDifficulty.EASY,
        ),
    }
)

_ACTION_IDS_BY_FACTOR = {
    ReportFactorCode.SLEEP_DECREASE: (RecoveryActionId.SLEEP_EARLY_60,),
    ReportFactorCode.WORKLOAD_INCREASE: (
        RecoveryActionId.SCHEDULE_REDUCE_ONE,
        RecoveryActionId.REST_30,
    ),
    ReportFactorCode.SCHEDULE_OVERLOAD: (
        RecoveryActionId.SCHEDULE_REDUCE_ONE,
        RecoveryActionId.REST_30,
    ),
    ReportFactorCode.REST_DECREASE: (RecoveryActionId.REST_30,),
    ReportFactorCode.EXERCISE_DECREASE: (
        RecoveryActionId.LIGHT_ACTIVITY_20,
    ),
    ReportFactorCode.NEGATIVE_EMOTION_INCREASE: (
        RecoveryActionId.JOURNAL_CHECKIN_10,
    ),
    ReportFactorCode.HIGH_NEGATIVE_EMOTION: (
        RecoveryActionId.JOURNAL_CHECKIN_10,
    ),
    ReportFactorCode.SUBJECTIVE_STRESS: (
        RecoveryActionId.REST_30,
        RecoveryActionId.JOURNAL_CHECKIN_10,
    ),
    ReportFactorCode.SUBJECTIVE_FATIGUE: (
        RecoveryActionId.REST_30,
        RecoveryActionId.LIGHT_ACTIVITY_20,
    ),
}


def get_recovery_action(action_id: RecoveryActionId) -> RecoveryAction:
    return _ACTIONS[action_id].model_copy(deep=True)


def select_recovery_actions(
    factor_codes: list[ReportFactorCode],
    *,
    limit: int = 3,
) -> list[RecoveryAction]:
    if limit < 1 or limit > 3:
        raise ValueError("recovery action limit must be between one and three")

    selected: list[RecoveryActionId] = []
    for factor_code in factor_codes:
        for action_id in _ACTION_IDS_BY_FACTOR[factor_code]:
            if action_id not in selected:
                selected.append(action_id)
            if len(selected) == limit:
                break
        if len(selected) == limit:
            break

    if not selected:
        selected.append(RecoveryActionId.ROUTINE_CHECK_5)
    return [get_recovery_action(action_id) for action_id in selected]


__all__ = [
    "CATALOG_VERSION",
    "get_recovery_action",
    "select_recovery_actions",
]
