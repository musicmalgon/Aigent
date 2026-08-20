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
        RecoveryActionId.BREATHING_5: RecoveryAction(
            id=RecoveryActionId.BREATHING_5,
            title="호흡 정리 5분",
            duration_minutes=5,
            difficulty=RecoveryDifficulty.EASY,
        ),
        RecoveryActionId.TALK_TO_SOMEONE: RecoveryAction(
            id=RecoveryActionId.TALK_TO_SOMEONE,
            title="가까운 사람과 짧은 대화",
            duration_minutes=10,
            difficulty=RecoveryDifficulty.EASY,
        ),
        RecoveryActionId.SMALL_SUCCESS_TASK: RecoveryAction(
            id=RecoveryActionId.SMALL_SUCCESS_TASK,
            title="작은 성취 과제 하나 끝내기",
            duration_minutes=5,
            difficulty=RecoveryDifficulty.EASY,
        ),
        RecoveryActionId.STEP_AWAY_5: RecoveryAction(
            id=RecoveryActionId.STEP_AWAY_5,
            title="자리에서 잠시 벗어나기",
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

# Stage 2 labels are mapped to low-intensity actions only. They are
# informational and never alter the burnout risk score.
_ACTION_IDS_BY_STAGE2_SIGNAL = {
    "exhaustion": (RecoveryActionId.REST_30, RecoveryActionId.SLEEP_EARLY_60),
    "overload": (
        RecoveryActionId.SCHEDULE_REDUCE_ONE,
        RecoveryActionId.REST_30,
    ),
    "helplessness": (
        RecoveryActionId.ROUTINE_CHECK_5,
        RecoveryActionId.JOURNAL_CHECKIN_10,
    ),
    "low_efficacy": (
        RecoveryActionId.ROUTINE_CHECK_5,
        RecoveryActionId.SCHEDULE_REDUCE_ONE,
    ),
    "anxiety": (
        RecoveryActionId.JOURNAL_CHECKIN_10,
        RecoveryActionId.REST_30,
    ),
    "irritability": (
        RecoveryActionId.REST_30,
        RecoveryActionId.SCHEDULE_REDUCE_ONE,
    ),
}

# Every report should offer a small, usable starting set even when the
# baseline has too few records to produce behavioral factors.  Contextual
# actions are selected first; these low-intensity defaults fill the remaining
# slots so the UI does not collapse to a single generic recommendation.
_DEFAULT_ACTION_IDS = (
    RecoveryActionId.REST_30,
    RecoveryActionId.LIGHT_ACTIVITY_20,
    RecoveryActionId.ROUTINE_CHECK_5,
)

_CANDIDATE_TO_ACTION = {
    "rest_30min": RecoveryActionId.REST_30,
    "light_move_20min": RecoveryActionId.LIGHT_ACTIVITY_20,
    "daily_rhythm_check_5min": RecoveryActionId.ROUTINE_CHECK_5,
    "reduce_task_one": RecoveryActionId.SCHEDULE_REDUCE_ONE,
    "breathing_5min": RecoveryActionId.BREATHING_5,
    "talk_to_someone": RecoveryActionId.TALK_TO_SOMEONE,
    "small_success_task": RecoveryActionId.SMALL_SUCCESS_TASK,
    "sleep_prep_routine": RecoveryActionId.SLEEP_EARLY_60,
    "step_away_5min": RecoveryActionId.STEP_AWAY_5,
}

_CANDIDATE_SIGNALS = {
    "rest_30min": ("exhaustion", "overload", "default"),
    "light_move_20min": ("exhaustion", "low_efficacy", "default"),
    "daily_rhythm_check_5min": ("default",),
    "reduce_task_one": ("overload",),
    "breathing_5min": ("anxiety", "irritability"),
    "talk_to_someone": ("helplessness", "anxiety"),
    "small_success_task": ("low_efficacy", "helplessness"),
    "sleep_prep_routine": ("exhaustion", "irritability", "default"),
    "step_away_5min": ("irritability", "overload"),
}

_CANDIDATE_DESCRIPTIONS = {
    "rest_30min": "알림을 끄고 최소 30분간 휴식에만 집중하기",
    "light_move_20min": "가벼운 산책, 스트레칭 등 20분 활동",
    "daily_rhythm_check_5min": "수면·식사·활동 시간을 5분간 되돌아보기",
    "reduce_task_one": "오늘 계획 중 하나를 미루거나 위임하기",
    "breathing_5min": "천천히 심호흡하며 긴장 낮추기",
    "talk_to_someone": "가족·친구·동료와 5~10분 가벼운 대화",
    "small_success_task": "5분 내 끝낼 수 있는 아주 작은 일 완료하기",
    "sleep_prep_routine": "화면 끄고 조명 낮추는 등 취침 준비",
    "step_away_5min": "5분간 하던 일에서 물리적으로 떨어지기",
}


def get_recovery_action(action_id: RecoveryActionId) -> RecoveryAction:
    return _ACTIONS[action_id].model_copy(deep=True)


def recovery_candidate_pool() -> list[dict[str, object]]:
    """Return the fixed, LLM-selectable candidate pool."""
    return [
        {
            "id": candidate_id,
            "label": get_recovery_action(action_id).title,
            "description": _CANDIDATE_DESCRIPTIONS[candidate_id],
            "signals": list(_CANDIDATE_SIGNALS[candidate_id]),
        }
        for candidate_id, action_id in _CANDIDATE_TO_ACTION.items()
    ]


def actions_from_candidate_ids(candidate_ids: list[str]) -> list[RecoveryAction]:
    """Validate candidate IDs and map them to the public action contract."""
    if not 1 <= len(candidate_ids) <= 3:
        raise ValueError("candidate selection must contain one to three ids")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("candidate selection must not contain duplicates")
    try:
        action_ids = [
            _CANDIDATE_TO_ACTION[candidate_id] for candidate_id in candidate_ids
        ]
    except KeyError as exc:
        raise ValueError("candidate selection contains an unknown id") from exc
    return [get_recovery_action(action_id) for action_id in action_ids]


def select_default_recovery_actions(limit: int = 3) -> list[RecoveryAction]:
    if limit < 1 or limit > 3:
        raise ValueError("recovery action limit must be between one and three")
    return [get_recovery_action(action_id) for action_id in _DEFAULT_ACTION_IDS[:limit]]


def select_recovery_actions(
    factor_codes: list[ReportFactorCode],
    *,
    stage2_signals: list[str] | tuple[str, ...] = (),
    limit: int = 3,
) -> list[RecoveryAction]:
    if limit < 1 or limit > 3:
        raise ValueError("recovery action limit must be between one and three")

    selected: list[RecoveryActionId] = []
    # Calibrated Stage 2 drivers take precedence, while behavioral factors
    # fill any remaining slots. This makes the new signal path observable
    # without allowing it to replace the existing risk engine.
    for signal in stage2_signals:
        for action_id in _ACTION_IDS_BY_STAGE2_SIGNAL.get(signal, ()):
            if action_id not in selected:
                selected.append(action_id)
            if len(selected) == limit:
                break
        if len(selected) == limit:
            break

    if len(selected) < limit:
        for factor_code in factor_codes:
            for action_id in _ACTION_IDS_BY_FACTOR[factor_code]:
                if action_id not in selected:
                    selected.append(action_id)
                if len(selected) == limit:
                    break
            if len(selected) == limit:
                break

    if len(selected) < limit:
        for action_id in _DEFAULT_ACTION_IDS:
            if action_id not in selected:
                selected.append(action_id)
            if len(selected) == limit:
                break
    return [get_recovery_action(action_id) for action_id in selected]


__all__ = [
    "CATALOG_VERSION",
    "get_recovery_action",
    "select_recovery_actions",
    "recovery_candidate_pool",
    "actions_from_candidate_ids",
    "select_default_recovery_actions",
]
