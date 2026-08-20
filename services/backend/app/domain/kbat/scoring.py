"""K-BAT(한국판 직무소진평가척도) 채점 -- 유일한 계산 지점.

문항 응답(1~5) -> 하위영역 평균 -> 전체 평균 -> 위험도 판정까지 전부 이
모듈을 거치게 해서, 같은 계산이 화면마다(웹/모바일/리포트 등) 따로
구현되며 갈라지는 일을 막는다. I/O나 영속성에는 관여하지 않는다.
"""

from __future__ import annotations

from .models import LIKERT_MAX, LIKERT_MIN, KBatDomainScores, KBatResult, KBatRiskLevel

# 요구사항의 경계값(2.53→양호, 2.54→주의, 2.95→주의, 2.96→경고)은 소수
# 둘째 자리까지 반올림한 값 기준이다. 반올림을 판정 시점에 다시 하면
# 부동소수점 오차로 경계값이 흔들릴 수 있으므로, 대신 두 경계 구간의
# 정중앙(2.535, 2.955)을 원시(반올림 전) 평균과 비교한다. 이렇게 하면
# "반올림 후 비교"와 결과가 항상 같으면서도 반올림을 판정에서 완전히
# 분리할 수 있다 -- 화면 표시용 반올림은 별도로 수행한다(round_for_display).
_GOOD_CAUTION_BOUNDARY = 2.535
_CAUTION_WARNING_BOUNDARY = 2.955


def classify_risk_level(total_average: float) -> KBatRiskLevel:
    """전체 평균(원시값)을 3단계 위험도로 판정한다.

    1.00~2.53 양호 · 2.54~2.95 주의 · 2.96~5.00 경고.
    """
    if not (LIKERT_MIN <= total_average <= LIKERT_MAX):
        raise ValueError(
            f"total_average must be within {LIKERT_MIN}~{LIKERT_MAX}, got {total_average}"
        )
    if total_average < _GOOD_CAUTION_BOUNDARY:
        return KBatRiskLevel.GOOD
    if total_average < _CAUTION_WARNING_BOUNDARY:
        return KBatRiskLevel.CAUTION
    return KBatRiskLevel.WARNING


def round_for_display(value: float, digits: int = 2) -> float:
    """화면 표시 전용 반올림. 판정(classify_risk_level)에는 절대 쓰지 않는다."""
    return round(value, digits)


def calculate_domain_average(answers: list[float]) -> float | None:
    """한 하위영역의 문항 점수(1~5) 목록을 평균낸다.

    응답이 하나도 없으면 None -- 임의로 0이나 중간값을 채워 넣어 정상
    데이터처럼 보이게 하지 않는다. 호출부는 None을 "이 영역은 판단할 수
    없음"으로 취급해야 한다.
    """
    if not answers:
        return None
    for value in answers:
        if not (LIKERT_MIN <= value <= LIKERT_MAX):
            raise ValueError(
                f"K-BAT answers must be within {LIKERT_MIN}~{LIKERT_MAX}, got {value}"
            )
    return sum(answers) / len(answers)


def calculate_burnout_result(domain_scores: KBatDomainScores) -> KBatResult:
    """4개 하위영역 평균으로 전체 평균과 위험도를 계산한다.

    전체 평균은 "문항 전체를 다시 평균"이 아니라 "4개 영역 평균의 평균"으로
    정의한다. 영역별 문항 수가 다르기 때문이다(탈진 8 / 심적거리 4 /
    인지적 조절손상 5 / 정서적 조절손상 5) -- 문항 기준으로 평균을 내면
    문항이 가장 많은 탈진 영역에 결과가 쏠린다. 4개 영역을 동일 가중치로
    다뤄야 화면에 보여줄 "영역별 평균"과 "전체 평균"의 계산 기준이 서로
    어긋나지 않는다.
    """
    averages = (
        domain_scores.exhaustion,
        domain_scores.mental_distance,
        domain_scores.cognitive_control,
        domain_scores.emotional_control,
    )
    total_average = sum(averages) / len(averages)
    return KBatResult(
        exhaustion_average=domain_scores.exhaustion,
        mental_distance_average=domain_scores.mental_distance,
        cognitive_control_average=domain_scores.cognitive_control,
        emotional_control_average=domain_scores.emotional_control,
        total_average=total_average,
        risk_level=classify_risk_level(total_average),
    )


__all__ = [
    "calculate_burnout_result",
    "calculate_domain_average",
    "classify_risk_level",
    "round_for_display",
]
