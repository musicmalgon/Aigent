"""사용자가 직접 요청한 계정 삭제 -- 파생 데이터와 계정 자체를 모두 지운다.

원래는 파생 데이터만 지우고 계정(`users`)과 동의 이력(`consent_records`)은
감사 추적을 위해 보존했었다. 하지만 그 설계가 프론트 UI 문구("계정 삭제")와
어긋난다는 문제(#133)로, 계정 자체도 지우는 진짜 삭제로 바뀌었다. 재로그인이
아예 불가능해지므로 동의 이력을 감사 추적용으로 남겨둘 이유도 없어져서 함께
지운다.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.assessments import delete_all_assessment_anchors_for_user
from app.repositories.baselines import delete_all_baselines_for_user
from app.repositories.behavioral_records import delete_all_daily_records_for_user
from app.repositories.consent import delete_all_consent_records_for_user
from app.repositories.emotion_results import delete_all_emotion_results_for_user
from app.repositories.recovery_plan_items import (
    delete_all_recovery_plan_items_for_user,
)
from app.repositories.recovery_reports import delete_all_recovery_reports_for_user
from app.repositories.risk_evaluations import delete_all_risk_evaluations_for_user


@dataclass(frozen=True)
class AccountDataDeletionSummary:
    recovery_plan_items_deleted: int
    recovery_reports_deleted: int
    risk_evaluations_deleted: int
    baselines_deleted: int
    emotion_analyses_deleted: int
    daily_records_deleted: int
    consent_records_deleted: int
    assessment_anchors_deleted: int


def delete_all_account_data(
    session: Session,
    *,
    user: User,
) -> AccountDataDeletionSummary:
    """users.id를 참조하는 테이블 7개를 자식→부모 순서로 지우고, 마지막에
    계정(users) 행 자체를 지운다. 테이블별 삭제 건수를 돌려준다.

    FK가 대부분 CASCADE/SET NULL이라 순서 없이도 결과는 같지만, 명시적으로
    지워야 무엇이 지워지는지가 코드만 읽어도 드러나고 건수를 테이블별로 셀 수
    있다. 커밋은 호출자(API 계층)가 한다.
    """

    recovery_plan_items = delete_all_recovery_plan_items_for_user(
        session,
        user_id=user.id,
    )
    recovery_reports = delete_all_recovery_reports_for_user(
        session,
        user_id=user.id,
    )
    risk_evaluations = delete_all_risk_evaluations_for_user(
        session,
        user_id=user.id,
    )
    baselines = delete_all_baselines_for_user(session, user_id=user.id)
    emotion_analyses = delete_all_emotion_results_for_user(
        session,
        user_id=user.id,
    )
    daily_records = delete_all_daily_records_for_user(session, user_id=user.id)
    consent_records = delete_all_consent_records_for_user(session, user_id=user.id)
    assessment_anchors = delete_all_assessment_anchors_for_user(
        session,
        user_id=user.id,
    )

    session.delete(user)

    return AccountDataDeletionSummary(
        recovery_plan_items_deleted=recovery_plan_items,
        recovery_reports_deleted=recovery_reports,
        risk_evaluations_deleted=risk_evaluations,
        baselines_deleted=baselines,
        emotion_analyses_deleted=emotion_analyses,
        daily_records_deleted=daily_records,
        consent_records_deleted=consent_records,
        assessment_anchors_deleted=assessment_anchors,
    )


__all__ = [
    "AccountDataDeletionSummary",
    "delete_all_account_data",
]
