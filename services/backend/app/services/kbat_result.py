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

from app.domain.kbat import (
    LIKERT_MAX,
    LIKERT_MIN,
    KBatDomainScores,
    KBatResult,
    calculate_burnout_result,
)
from app.models.assessment import AssessmentAnchor, AssessmentType
from app.repositories.assessments import get_latest_assessment_anchor
from app.repositories.behavioral_records import count_daily_records
from app.services.baselines import MINIMUM_SAMPLE_DAYS

# BurnoutFlow(K-BAT 온보딩 설문)가 앵커를 저장할 때 쓰는 source 값.
# 과거(리커트 0~4를 0~1 소진 강도로 반전 환산하던) 버전과 척도 자체가
# 다르므로 이름을 구분한다 -- 옛 데이터를 지우지는 않되, 그대로 새 채점
# 로직에 흘려 넣지 않고 아래 _convert_legacy_dimension으로 변환해서 쓴다.
KBAT_SURVEY_SOURCE = "onboarding_kbat_v2"

_DOMAIN_KEYS = ("exhaustion", "mental_distance", "cognitive_control", "emotional_control")


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
    is_legacy = False
    if anchor is None:
        # v2로 응답한 적은 없어도, 이 세션 이전(구 채점 방식)에 K-BAT을
        # 이미 완료한 사용자가 있을 수 있다. 그 응답을 그냥 버려서
        # "설문을 아예 안 한 사람"처럼 보이게 하면 안 된다 -- 다시 설문을
        # 받게 하는 대신 구버전 응답을 새 척도로 환산해서 쓴다.
        anchor = get_latest_assessment_anchor(
            session,
            user_id=user_id,
            assessment_type=AssessmentType.K_BAT,
        )
        is_legacy = anchor is not None

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

    domain_scores = _domain_scores_from_anchor(anchor, is_legacy=is_legacy)
    result = calculate_burnout_result(domain_scores)
    return KBatResultSnapshot(
        state=KBatResultState.READY,
        recorded_days=recorded_days,
        minimum_required_days=minimum_required_days,
        survey_completed_at=anchor.completed_at,
        result=result,
    )


def _convert_legacy_dimension(value: float | None) -> float | None:
    """구버전(리커트 0~4를 0~1 소진 강도로 반전 환산) 값을 새 리커트
    원점수(1~5) 스케일로 되돌린다.

    두 척도 모두 "값이 클수록 번아웃 증상에 더 동의함"이라는 방향은
    같다(구버전 0=부담 없음~1=부담 큼, 신버전 1=전혀 그렇지 않다~5=항상
    그렇다) -- 부호를 뒤집을 필요 없이 [0,1]을 [1,5]로 선형 확장하면 된다.
    """
    if value is None:
        return None
    converted = 1.0 + (LIKERT_MAX - LIKERT_MIN) * value
    return max(LIKERT_MIN, min(LIKERT_MAX, converted))


def _domain_scores_from_anchor(
    anchor: AssessmentAnchor,
    *,
    is_legacy: bool,
) -> KBatDomainScores:
    # dimensions는 자유 형식 JSON(app/models/assessment.py)이지만, 새
    # 버전(source=KBAT_SURVEY_SOURCE)으로 저장되는 값은 항상 프론트
    # (BurnoutFlow)가 4개 영역 전부를 채워 보낸다 -- 화면이 모든 문항
    # 응답을 받아야만 "다음"을 누를 수 있게 막아두었기 때문. 구버전도
    # 같은 제약으로 저장됐다. 그래도 값이 예상과 다르면(예: 수동으로
    # 잘못 들어간 데이터) 감춰서 0으로 보여주지 않고 그대로 예외를 올려
    # 500으로 드러낸다.
    raw = anchor.dimensions
    if not is_legacy:
        return KBatDomainScores.model_validate(raw)
    converted = {key: _convert_legacy_dimension(raw.get(key)) for key in _DOMAIN_KEYS}
    return KBatDomainScores.model_validate(converted)


__all__ = [
    "KBAT_SURVEY_SOURCE",
    "KBatResultSnapshot",
    "KBatResultState",
    "gather_kbat_result",
]
