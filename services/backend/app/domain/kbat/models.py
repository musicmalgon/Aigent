"""Validated public models for K-BAT(한국판 직무소진평가척도) 자가진단 채점.

번아웃 위험도 계산과 무관한 다른 도메인(app/domain/risk)과 이름이 겹치지
않도록 별도 서브패키지로 둔다. 여기 모델은 순수 값 객체이며 DB나 API
스키마에 의존하지 않는다 -- 저장/응답 형식은 app/services, app/schemas가
이 모델을 감싸서 만든다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# 리커트 5점 척도 원점수 범위. "전혀 그렇지 않다"=1 ~ "항상 그렇다"=5.
LIKERT_MIN = 1.0
LIKERT_MAX = 5.0

LikertAverage = Field(ge=LIKERT_MIN, le=LIKERT_MAX)


class KBatDomain(StrEnum):
    """K-BAT 4개 하위영역. app/schemas/assessment.py의 DimensionKey 값과 1:1로 맞춘다."""

    EXHAUSTION = "exhaustion"
    MENTAL_DISTANCE = "mental_distance"
    COGNITIVE_CONTROL = "cognitive_control"
    EMOTIONAL_CONTROL = "emotional_control"


class KBatRiskLevel(StrEnum):
    """전체 평균 기준 3단계 판정."""

    GOOD = "good"  # 양호 · 안전
    CAUTION = "caution"  # 주의 · 위험군
    WARNING = "warning"  # 경고 · 고위험군


class KBatDomainScores(BaseModel):
    """4개 하위영역의 원점수(1~5) 평균. 하나라도 없으면 계산 자체를 할 수 없다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exhaustion: float = LikertAverage
    mental_distance: float = LikertAverage
    cognitive_control: float = LikertAverage
    emotional_control: float = LikertAverage


class KBatResult(BaseModel):
    """4개 영역 평균 + 전체 평균 + 위험도. 화면은 이 값을 그대로 렌더링한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exhaustion_average: float = LikertAverage
    mental_distance_average: float = LikertAverage
    cognitive_control_average: float = LikertAverage
    emotional_control_average: float = LikertAverage
    total_average: float = LikertAverage
    risk_level: KBatRiskLevel


__all__ = [
    "LIKERT_MAX",
    "LIKERT_MIN",
    "KBatDomain",
    "KBatDomainScores",
    "KBatResult",
    "KBatRiskLevel",
]
