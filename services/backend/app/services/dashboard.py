"""홈 화면용 읽기 전용 집계 — 새로 계산하지 않고 최신 산출물만 모은다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy.orm import Session

from app.models.persistence import (
    BehavioralBaseline,
    BurnoutRiskEvaluation,
    PersistenceBaselineStatus,
    RecoveryReport,
)
from app.repositories.baselines import get_latest_ready_baseline
from app.repositories.behavioral_records import (
    count_daily_records,
    get_daily_record_by_date,
)
from app.repositories.recovery_reports import get_latest_recovery_report
from app.repositories.risk_evaluations import get_latest_dated_risk_evaluation
from app.services.baselines import MINIMUM_SAMPLE_DAYS


@dataclass(frozen=True)
class UserStatusSnapshot:
    today_recorded: bool
    # 전체 기간 기록 수. services/baselines.py의 실제 임계 로직(계산 시점의
    # 롤링 윈도우)을 다시 구현한 게 아니라 UI 힌트용 근사치다. 진짜 판정은
    # POST /api/v1/baselines가 내린다.
    recorded_days: int
    latest_baseline: BehavioralBaseline | None
    latest_risk_evaluation: BurnoutRiskEvaluation | None
    latest_recovery_report: RecoveryReport | None


def gather_user_status(
    db: Session,
    *,
    user_id: str,
    today: date,
) -> UserStatusSnapshot:
    return UserStatusSnapshot(
        today_recorded=get_daily_record_by_date(
            db,
            user_id=user_id,
            record_date=today,
        )
        is not None,
        recorded_days=count_daily_records(db, user_id=user_id),
        latest_baseline=get_latest_ready_baseline(db, user_id=user_id),
        latest_risk_evaluation=get_latest_dated_risk_evaluation(
            db,
            user_id=user_id,
        ),
        latest_recovery_report=get_latest_recovery_report(db, user_id=user_id),
    )


class ReadinessState(StrEnum):
    INSUFFICIENT_RECORDS = "insufficient_records"
    BASELINE_PENDING = "baseline_pending"
    BASELINE_READY = "baseline_ready"
    RISK_EVALUATION_READY = "risk_evaluation_ready"
    RECOVERY_REPORT_READY = "recovery_report_ready"


def classify_readiness(snapshot: UserStatusSnapshot) -> ReadinessState:
    """5단계 퍼널을 가장 진행된 상태부터 거꾸로 판정한다.

    각 상태는 "지금 이 사용자에게 존재하는 가장 앞선 산출물"을 뜻하지
    "사용자가 이제 무엇을 요청할 수 있는지"를 뜻하지 않는다. 이름만 보면
    (예: "Risk Evaluation 가능") 두 해석이 모두 가능해서 애매한데,
    RECOVERY_REPORT_READY가 명백히 "리포트가 존재한다"는 뜻이므로
    대칭을 맞춰 전자를 택했다. 위에서 아래로 내려가는 순서 자체가
    단조성(monotonic)을 보장한다.
    """
    if snapshot.latest_recovery_report is not None:
        return ReadinessState.RECOVERY_REPORT_READY
    if snapshot.latest_risk_evaluation is not None:
        return ReadinessState.RISK_EVALUATION_READY
    if (
        snapshot.latest_baseline is not None
        and snapshot.latest_baseline.status is PersistenceBaselineStatus.READY
    ):
        return ReadinessState.BASELINE_READY
    if snapshot.recorded_days >= MINIMUM_SAMPLE_DAYS:
        return ReadinessState.BASELINE_PENDING
    return ReadinessState.INSUFFICIENT_RECORDS


__all__ = [
    "ReadinessState",
    "UserStatusSnapshot",
    "classify_readiness",
    "gather_user_status",
]
