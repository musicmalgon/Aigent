"""사용자가 직접 요청한 건강/행동 파생 데이터 일괄 삭제.

계정(`users`)과 동의 이력(`consent_records`)은 건드리지 않는다. 동의를 언제
주고 언제 데이터를 지웠는지에 대한 감사 기록은 삭제 요청과 무관하게 남아야
하고, 사용자는 삭제 후에도 같은 계정으로 다시 기록을 시작할 수 있어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.repositories.baselines import delete_all_baselines_for_user
from app.repositories.behavioral_records import delete_all_daily_records_for_user
from app.repositories.emotion_results import delete_all_emotion_results_for_user
from app.repositories.recovery_reports import delete_all_recovery_reports_for_user
from app.repositories.risk_evaluations import delete_all_risk_evaluations_for_user


@dataclass(frozen=True)
class AccountDataDeletionSummary:
    recovery_reports_deleted: int
    risk_evaluations_deleted: int
    baselines_deleted: int
    emotion_analyses_deleted: int
    daily_records_deleted: int


def delete_all_account_data(
    session: Session,
    *,
    user_id: str,
) -> AccountDataDeletionSummary:
    """5개 파생 테이블을 자식→부모 순서로 지우고 테이블별 삭제 건수를 돌려준다.

    FK가 이미 CASCADE/SET NULL이라 순서 없이도 결과는 같지만, 명시적으로 지워야
    무엇이 지워지는지가 코드만 읽어도 드러나고 건수를 테이블별로 셀 수 있다.
    커밋은 호출자(API 계층)가 한다.
    """

    recovery_reports = delete_all_recovery_reports_for_user(
        session,
        user_id=user_id,
    )
    risk_evaluations = delete_all_risk_evaluations_for_user(
        session,
        user_id=user_id,
    )
    baselines = delete_all_baselines_for_user(session, user_id=user_id)
    emotion_analyses = delete_all_emotion_results_for_user(
        session,
        user_id=user_id,
    )
    daily_records = delete_all_daily_records_for_user(session, user_id=user_id)

    return AccountDataDeletionSummary(
        recovery_reports_deleted=recovery_reports,
        risk_evaluations_deleted=risk_evaluations,
        baselines_deleted=baselines,
        emotion_analyses_deleted=emotion_analyses,
        daily_records_deleted=daily_records,
    )


__all__ = [
    "AccountDataDeletionSummary",
    "delete_all_account_data",
]
