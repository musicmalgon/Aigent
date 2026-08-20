"""K-BAT 자가진단 결과 = 설문 응답 + 누적 일상기록.

요구사항: 설문을 완료했다고 바로 최종 결과를 보여주지 않는다. 사용자가
일상기록을 최소 7일 실제로 쌓아야 결과를 계산해서 보여준다. "7일"은
가입일 + 7일 같은 달력 기준이 아니라, 실제로 기록이 존재하는 날짜 수
기준이다 -- app/services/baselines.py가 이미 같은 정의(실제 기록된
날짜 집합의 크기)로 MINIMUM_SAMPLE_DAYS를 쓰고 있으므로 그대로 재사용해
"7일"의 정의가 기능마다 갈라지지 않게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from app.domain.kbat import KBatDomainScores, KBatResult, calculate_burnout_result
from app.models.assessment import AssessmentAnchor, AssessmentType
from app.repositories.assessments import get_latest_assessment_anchor
from app.repositories.behavioral_records import count_daily_records
from app.services.baselines import MINIMUM_SAMPLE_DAYS

# BurnoutFlow(K-BAT 온보딩 설문)가 앵커를 저장할 때 쓰는 source 값.
# 과거(리커트 0~4를 0~1 소진 강도로 반전 환산하던) 버전과 척도 자체가
# 다르므로 이름을 구분해, 옛 데이터가 새 채점 로직으로 잘못 읽히지 않게
# 한다 -- 기존 사용자의 예전 K-BAT 응답은 그대로 두고 무시할 뿐 지우지
# 않는다.
KBAT_SURVEY_SOURCE = "onboarding_kbat_v2"


class KBatResultState(StrEnum):
    NOT_TAKEN = "not_taken"
    """K-BAT 설문(v2)을 아직 완료하지 않음."""
    INSUFFICIENT_RECORDS = "insufficient_records"
    """설문은 완료했지만 일상기록이 아직 최소 일수(7일) 미만."""
    READY = "ready"
    """설문 + 충분한 일상기록으로 결과를 계산할 수 있음."""


@dataclass(frozen=True)
class KBatResultSnapshot:
    state: KBatResultState
    recorded_days: int
    minimum_required_days: int
    survey_completed_at: datetime | None
    result: KBatResult | None


def gather_kbat_result(
    session: Session,
    *,
    user_id: str,
    minimum_required_days: int = MINIMUM_SAMPLE_DAYS,
) -> KBatResultSnapshot:
    anchor = get_latest_assessment_anchor(
        session,
        user_id=user_id,
        assessment_type=AssessmentType.K_BAT,
        source=KBAT_SURVEY_SOURCE,
    )
    recorded_days = count_daily_records(session, user_id=user_id)

    if anchor is None:
        return KBatResultSnapshot(
            state=KBatResultState.NOT_TAKEN,
            recorded_days=recorded_days,
            minimum_required_days=minimum_required_days,
            survey_completed_at=None,
            result=None,
        )

    if recorded_days < minimum_required_days:
        return KBatResultSnapshot(
            state=KBatResultState.INSUFFICIENT_RECORDS,
            recorded_days=recorded_days,
            minimum_required_days=minimum_required_days,
            survey_completed_at=anchor.completed_at,
            result=None,
        )

    result = calculate_burnout_result(_domain_scores_from_anchor(anchor))
    return KBatResultSnapshot(
        state=KBatResultState.READY,
        recorded_days=recorded_days,
        minimum_required_days=minimum_required_days,
        survey_completed_at=anchor.completed_at,
        result=result,
    )


def _domain_scores_from_anchor(anchor: AssessmentAnchor) -> KBatDomainScores:
    # dimensions는 자유 형식 JSON(app/models/assessment.py)이지만, 이
    # source(KBAT_SURVEY_SOURCE)로 저장되는 값은 항상 프론트(BurnoutFlow)가
    # 4개 영역 전부를 채워 보낸다 -- 화면이 모든 문항 응답을 받아야만
    # "다음"을 누를 수 있게 막아두었기 때문. 그래도 저장된 값이 예상과
    # 다르면(예: 수동으로 잘못 들어간 데이터) 감춰서 0으로 보여주지 않고
    # 그대로 예외를 올려 500으로 드러낸다.
    return KBatDomainScores.model_validate(anchor.dimensions)


__all__ = [
    "KBAT_SURVEY_SOURCE",
    "KBatResultSnapshot",
    "KBatResultState",
    "gather_kbat_result",
]
