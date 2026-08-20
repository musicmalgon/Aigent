from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.clients.ai import (
    AIServiceClient,
    AIServiceError,
    RecoveryActionSelectionRequest,
)
from app.domain.recovery.catalog import (
    actions_from_candidate_ids,
    recovery_candidate_pool,
    select_default_recovery_actions,
    select_recovery_actions,
)
from app.domain.recovery.models import (
    RecoveryActionId,
    RecoveryChangedItem,
    RecoveryRecommendationDescription,
    RecoveryReportChange,
    RecoveryReportCopy,
    RecoveryReportGenerationRequest,
    RecoveryReportPeriod,
    ReportFactorCode,
    ReportGenerationStatus,
    ReportMetric,
)
from app.domain.risk.models import (
    BurnoutRiskEvaluationResponse,
    FactorCode,
    RiskFactor,
)
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    RecoveryReport,
)
from app.repositories.baselines import get_baseline
from app.repositories.behavioral_records import list_daily_records
from app.repositories.emotion_results import list_emotion_results_by_date_range
from app.repositories.recovery_reports import create_recovery_report
from app.repositories.risk_evaluations import get_risk_evaluation
from app.services.behavioral_record_mapper import (
    DailyRecordMetadataUnavailableError,
    to_daily_record_read,
)
from app.services.risk_evaluation_mapper import map_risk_evaluation_response

LOGGER = logging.getLogger(__name__)

REPORT_DISCLAIMER = (
    "이 결과는 생활 기록을 바탕으로 한 참고 정보이며 의료적 진단이 아닙니다."
)


class RiskEvaluationNotFoundError(LookupError):
    """The requested user has no usable risk evaluation with that id."""


class RecoveryReportInputUnavailableError(RuntimeError):
    """Source data cannot be represented without guessing."""


class RecoveryReportInputsChangedError(RuntimeError):
    """Prepared source data changed before report persistence."""


@dataclass(frozen=True)
class PreparedRecoveryReport:
    user_id: str
    risk_evaluation_id: str
    request: RecoveryReportGenerationRequest
    input_snapshot: str = field(repr=False)


_METRIC_BY_FACTOR = {
    ReportFactorCode.SLEEP_DECREASE: ReportMetric.SLEEP_MINUTES,
    ReportFactorCode.WORKLOAD_INCREASE: ReportMetric.WORK_OR_STUDY_MINUTES,
    ReportFactorCode.SCHEDULE_OVERLOAD: ReportMetric.SCHEDULE_COUNT,
    ReportFactorCode.REST_DECREASE: ReportMetric.REST_MINUTES,
    ReportFactorCode.EXERCISE_DECREASE: ReportMetric.EXERCISE_MINUTES,
    ReportFactorCode.NEGATIVE_EMOTION_INCREASE: (
        ReportMetric.NEGATIVE_EMOTION_PROBABILITY
    ),
    ReportFactorCode.HIGH_NEGATIVE_EMOTION: (
        ReportMetric.NEGATIVE_EMOTION_PROBABILITY
    ),
    ReportFactorCode.SUBJECTIVE_STRESS: ReportMetric.SUBJECTIVE_STRESS,
    ReportFactorCode.SUBJECTIVE_FATIGUE: ReportMetric.SUBJECTIVE_FATIGUE,
}

_DAILY_ATTRIBUTE_BY_METRIC = {
    ReportMetric.SLEEP_MINUTES: "sleep_minutes",
    ReportMetric.WORK_OR_STUDY_MINUTES: "study_work_minutes",
    ReportMetric.REST_MINUTES: "rest_minutes",
    ReportMetric.EXERCISE_MINUTES: "exercise_minutes",
    ReportMetric.SCHEDULE_COUNT: "schedule_count",
    ReportMetric.SUBJECTIVE_STRESS: "subjective_stress",
    ReportMetric.SUBJECTIVE_FATIGUE: "subjective_fatigue",
}

_BASELINE_ATTRIBUTE_BY_METRIC = {
    ReportMetric.SLEEP_MINUTES: "sleep_minutes",
    ReportMetric.WORK_OR_STUDY_MINUTES: "study_work_minutes",
    ReportMetric.REST_MINUTES: "rest_minutes",
    ReportMetric.EXERCISE_MINUTES: "exercise_minutes",
    ReportMetric.SCHEDULE_COUNT: "schedule_count",
    ReportMetric.NEGATIVE_EMOTION_PROBABILITY: "negative_emotion_probability",
    ReportMetric.SUBJECTIVE_STRESS: "subjective_stress",
    ReportMetric.SUBJECTIVE_FATIGUE: "subjective_fatigue",
}

_FACTOR_TITLE = {
    ReportFactorCode.SLEEP_DECREASE: "수면 시간이 줄었어요",
    ReportFactorCode.WORKLOAD_INCREASE: "업무·공부 시간이 늘었어요",
    ReportFactorCode.SCHEDULE_OVERLOAD: "일정이 평소보다 많았어요",
    ReportFactorCode.REST_DECREASE: "쉼 틈이 줄었어요",
    ReportFactorCode.EXERCISE_DECREASE: "가벼운 활동이 줄었어요",
    ReportFactorCode.NEGATIVE_EMOTION_INCREASE: "부정 감정 신호가 늘었어요",
    ReportFactorCode.HIGH_NEGATIVE_EMOTION: "부정 감정 신호가 높았어요",
    ReportFactorCode.SUBJECTIVE_STRESS: "주관적 스트레스가 높았어요",
    ReportFactorCode.SUBJECTIVE_FATIGUE: "주관적 피로가 높았어요",
}

_ACTION_REASON = {
    RecoveryActionId.REST_30: (
        "짧고 방해받지 않는 휴식 시간을 먼저 확보하기 위한 제안입니다."
    ),
    RecoveryActionId.SLEEP_EARLY_60: (
        "최근 수면 흐름을 평소 리듬에 조금 더 가깝게 조정하기 위한 제안입니다."
    ),
    RecoveryActionId.LIGHT_ACTIVITY_20: (
        "부담이 적은 움직임부터 생활 리듬에 다시 넣어 보기 위한 제안입니다."
    ),
    RecoveryActionId.SCHEDULE_REDUCE_ONE: (
        "오늘 해야 할 일의 부담을 한 단계 낮추기 위한 제안입니다."
    ),
    RecoveryActionId.JOURNAL_CHECKIN_10: (
        "현재 감정을 판단하지 않고 짧게 확인해 보기 위한 제안입니다."
    ),
    RecoveryActionId.ROUTINE_CHECK_5: (
        "현재 생활 리듬을 가볍게 점검하고 유지하기 위한 제안입니다."
    ),
    RecoveryActionId.BREATHING_5: (
        "호흡을 느리게 정리하며 긴장을 낮추기 위한 제안입니다."
    ),
    RecoveryActionId.TALK_TO_SOMEONE: (
        "가까운 사람과 연결감을 회복하기 위한 제안입니다."
    ),
    RecoveryActionId.SMALL_SUCCESS_TASK: (
        "작은 완료 경험으로 다시 시작하기 위한 제안입니다."
    ),
    RecoveryActionId.STEP_AWAY_5: (
        "하던 일에서 잠시 물리적으로 떨어져 과부하를 낮추기 위한 제안입니다."
    ),
}

_STAGE2_SIGNAL_ORDER = (
    "exhaustion",
    "overload",
    "helplessness",
    "low_efficacy",
    "anxiety",
    "irritability",
)


def _round(value: float | int | None) -> float | None:
    return round(float(value), 2) if value is not None else None


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _snapshot(payload: Any) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        default=_json_default,
        separators=(",", ":"),
        sort_keys=True,
    )


def _risk_result(
    evaluation: BurnoutRiskEvaluation,
) -> BurnoutRiskEvaluationResponse:
    return map_risk_evaluation_response(evaluation).result


def _report_factor_codes(
    result: BurnoutRiskEvaluationResponse,
) -> list[ReportFactorCode]:
    report_codes: list[ReportFactorCode] = []
    for code in result.summary.top_factor_codes:
        if code in {
            FactorCode.INSUFFICIENT_BASELINE,
            FactorCode.INSUFFICIENT_DATA,
        }:
            continue
        report_codes.append(ReportFactorCode(code.value))
    return report_codes


def _factor_by_code(
    result: BurnoutRiskEvaluationResponse,
) -> dict[ReportFactorCode, RiskFactor]:
    return {
        ReportFactorCode(factor.code.value): factor
        for factor in result.factors
        if factor.code
        not in {
            FactorCode.INSUFFICIENT_BASELINE,
            FactorCode.INSUFFICIENT_DATA,
        }
    }


def _stage2_signal_drivers(
    *,
    session: Session,
    user_id: str,
    start_date: date,
    end_date: date,
) -> list[str]:
    """Return validated active Stage 2 labels seen during the report window.

    The persistence payload is intentionally treated as untrusted provenance:
    only labels explicitly listed as both active and validated are eligible
    to influence recovery actions.
    """

    counts = {label: 0 for label in _STAGE2_SIGNAL_ORDER}
    seen_dates: set[date] = set()
    for result in list_emotion_results_by_date_range(
        session,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
    ):
        if result.record_date is None or result.record_date in seen_dates:
            continue
        seen_dates.add(result.record_date)
        payload = result.burnout_signal_payload
        if not isinstance(payload, dict):
            continue
        active = payload.get("active_signals")
        validated = payload.get("validated_signals")
        if not isinstance(active, list) or not isinstance(validated, list):
            continue
        eligible = set(active).intersection(validated)
        for label in _STAGE2_SIGNAL_ORDER:
            if label in eligible:
                counts[label] += 1
    return [
        label
        for label in _STAGE2_SIGNAL_ORDER
        if counts[label] > 0
    ]


def _average_metric(
    records: list[BehavioralDailyRecord],
    metric: ReportMetric,
) -> tuple[float | None, int]:
    attribute = _DAILY_ATTRIBUTE_BY_METRIC.get(metric)
    if attribute is None:
        return None, 0
    values = [
        float(value)
        for record in records
        if (value := getattr(record, attribute)) is not None
    ]
    if not values:
        return None, 0
    return round(sum(values) / len(values), 2), len(values)


def _format_number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _fact_text(
    *,
    metric: ReportMetric,
    recent_value: float,
    baseline_value: float | None,
    sample_days: int,
) -> str:
    metric_label = {
        ReportMetric.SLEEP_MINUTES: "수면 시간",
        ReportMetric.WORK_OR_STUDY_MINUTES: "업무·공부 시간",
        ReportMetric.REST_MINUTES: "휴식 시간",
        ReportMetric.EXERCISE_MINUTES: "운동 시간",
        ReportMetric.SCHEDULE_COUNT: "일정 수",
        ReportMetric.NEGATIVE_EMOTION_PROBABILITY: "부정 감정 신호",
        ReportMetric.SUBJECTIVE_STRESS: "주관적 스트레스",
        ReportMetric.SUBJECTIVE_FATIGUE: "주관적 피로",
    }[metric]
    if metric is ReportMetric.NEGATIVE_EMOTION_PROBABILITY:
        recent_display = f"{recent_value * 100:.1f}%"
        baseline_display = (
            f"{baseline_value * 100:.1f}%"
            if baseline_value is not None
            else None
        )
    else:
        unit = (
            "분"
            if metric
            in {
                ReportMetric.SLEEP_MINUTES,
                ReportMetric.WORK_OR_STUDY_MINUTES,
                ReportMetric.REST_MINUTES,
                ReportMetric.EXERCISE_MINUTES,
            }
            else "개"
            if metric is ReportMetric.SCHEDULE_COUNT
            else "점"
        )
        recent_display = f"{_format_number(recent_value)}{unit}"
        baseline_display = (
            f"{_format_number(baseline_value)}{unit}"
            if baseline_value is not None
            else None
        )
    period_text = (
        "평가일"
        if metric is ReportMetric.NEGATIVE_EMOTION_PROBABILITY
        else f"최근 7일 중 {sample_days}일 평균"
    )
    if baseline_display is None:
        return f"{period_text} {metric_label}은 {recent_display}입니다."
    return (
        f"{period_text} {metric_label}은 {recent_display}이고 "
        f"평소 기준은 {baseline_display}입니다."
    )


def _build_change(
    *,
    factor_code: ReportFactorCode,
    factor: RiskFactor,
    records: list[BehavioralDailyRecord],
    baseline: BehavioralBaseline,
) -> RecoveryReportChange | None:
    metric = _METRIC_BY_FACTOR[factor_code]
    if metric is ReportMetric.NEGATIVE_EMOTION_PROBABILITY:
        recent_value = _round(factor.observed_value)
        sample_days = 1 if recent_value is not None else 0
    else:
        recent_value, sample_days = _average_metric(records, metric)
    if recent_value is None:
        return None

    baseline_value = _round(
        getattr(baseline, _BASELINE_ATTRIBUTE_BY_METRIC[metric])
    )
    delta = (
        round(recent_value - baseline_value, 2)
        if baseline_value is not None
        else None
    )
    change_percent = None
    if baseline_value is not None and baseline_value != 0:
        change_percent = round(
            (recent_value - baseline_value) / baseline_value * 100,
            2,
        )
    return RecoveryReportChange(
        factor_code=factor_code,
        metric=metric,
        recent_value=recent_value,
        baseline_value=baseline_value,
        delta=delta,
        change_percent=change_percent,
        sample_days=sample_days,
        fact_text=_fact_text(
            metric=metric,
            recent_value=recent_value,
            baseline_value=baseline_value,
            sample_days=sample_days,
        ),
    )


def _source_snapshot(
    *,
    evaluation: BurnoutRiskEvaluation,
    baseline: BehavioralBaseline,
    records: list[BehavioralDailyRecord],
    request: RecoveryReportGenerationRequest,
) -> str:
    daily_snapshots: list[dict[str, Any]] = []
    for record in records:
        contract = to_daily_record_read(record)
        daily_snapshots.append(
            {
                "id": record.id,
                "contract": contract.model_dump(mode="json"),
                "subjective_stress": _round(record.subjective_stress),
                "updated_at": record.updated_at,
            }
        )
    request_payload = request.model_dump(mode="json")
    # Recommendations may be selected by a separate constrained LLM call;
    # source consistency is about records/baseline/risk inputs, not that choice.
    request_payload.pop("selected_actions", None)
    return _snapshot(
        {
            "risk_evaluation": {
                "id": evaluation.id,
                "record_date": evaluation.record_date,
                "daily_record_id": evaluation.daily_record_id,
                "baseline_id": evaluation.baseline_id,
                "engine_version": evaluation.engine_version,
                "score": evaluation.score,
                "level": evaluation.level,
                "is_provisional": evaluation.is_provisional,
                "data_quality": evaluation.data_quality,
                "category_scores": evaluation.category_scores,
                "factors": evaluation.factors,
                "summary": evaluation.summary,
                "created_at": evaluation.created_at,
            },
            "baseline": {
                "id": baseline.id,
                "window_start": baseline.window_start,
                "window_end": baseline.window_end,
                "sample_days": baseline.sample_days,
                "sleep_minutes": _round(baseline.sleep_minutes),
                "study_work_minutes": _round(baseline.study_work_minutes),
                "rest_minutes": _round(baseline.rest_minutes),
                "exercise_minutes": _round(baseline.exercise_minutes),
                "schedule_count": _round(baseline.schedule_count),
                "subjective_stress": _round(baseline.subjective_stress),
                "subjective_fatigue": _round(baseline.subjective_fatigue),
                "negative_emotion_probability": _round(
                    baseline.negative_emotion_probability
                ),
                "status": baseline.status,
                "algorithm_version": baseline.algorithm_version,
                "created_at": baseline.created_at,
            },
            "daily_records": daily_snapshots,
            "request": request_payload,
        }
    )


def _load_prepared(
    session: Session,
    *,
    user_id: str,
    risk_evaluation_id: str,
    for_update: bool,
) -> tuple[
    BurnoutRiskEvaluation,
    RecoveryReportGenerationRequest,
    str,
]:
    evaluation = get_risk_evaluation(
        session,
        user_id=user_id,
        evaluation_id=risk_evaluation_id,
        for_update=for_update,
    )
    if (
        evaluation is None
        or evaluation.record_date is None
        or evaluation.daily_record_id is None
        or evaluation.baseline_id is None
    ):
        raise RiskEvaluationNotFoundError

    baseline = get_baseline(
        session,
        user_id=user_id,
        baseline_id=evaluation.baseline_id,
        for_update=for_update,
    )
    if baseline is None:
        raise RecoveryReportInputUnavailableError(
            "risk evaluation baseline is unavailable"
        )

    period_start = evaluation.record_date - timedelta(days=6)
    records = list_daily_records(
        session,
        user_id=user_id,
        start_date=period_start,
        end_date=evaluation.record_date,
        for_update=for_update,
    )
    if not records or all(
        record.id != evaluation.daily_record_id for record in records
    ):
        raise RecoveryReportInputUnavailableError(
            "risk evaluation daily record is unavailable"
        )
    try:
        for record in records:
            to_daily_record_read(record)
        result = _risk_result(evaluation)
    except (
        DailyRecordMetadataUnavailableError,
        ValidationError,
        ValueError,
    ) as exc:
        raise RecoveryReportInputUnavailableError(
            "report inputs do not satisfy their public contracts"
        ) from exc

    factor_codes = _report_factor_codes(result)
    stage2_signal_drivers = _stage2_signal_drivers(
        session=session,
        user_id=user_id,
        start_date=period_start,
        end_date=evaluation.record_date,
    )
    factors = _factor_by_code(result)
    changes = [
        change
        for factor_code in factor_codes
        if (
            change := _build_change(
                factor_code=factor_code,
                factor=factors[factor_code],
                records=records,
                baseline=baseline,
            )
        )
        is not None
    ]
    request = RecoveryReportGenerationRequest(
        risk_level=result.level.value,
        risk_score=result.score,
        is_provisional=result.is_provisional,
        data_quality=result.data_quality.value,
        period=RecoveryReportPeriod(
            start=period_start,
            end=evaluation.record_date,
            record_days=len(records),
        ),
        changes=changes,
        selected_actions=select_recovery_actions(
            factor_codes,
            stage2_signals=stage2_signal_drivers,
        ),
        stage2_signal_drivers=stage2_signal_drivers,
    )
    return (
        evaluation,
        request,
        _source_snapshot(
            evaluation=evaluation,
            baseline=baseline,
            records=records,
            request=request,
        ),
    )


def prepare_recovery_report(
    session: Session,
    *,
    user_id: str,
    risk_evaluation_id: str,
) -> PreparedRecoveryReport:
    _, request, input_snapshot = _load_prepared(
        session,
        user_id=user_id,
        risk_evaluation_id=risk_evaluation_id,
        for_update=False,
    )
    return PreparedRecoveryReport(
        user_id=user_id,
        risk_evaluation_id=risk_evaluation_id,
        request=request,
        input_snapshot=input_snapshot,
    )


def build_template_fallback(
    request: RecoveryReportGenerationRequest,
) -> RecoveryReportCopy:
    changed_items = [
        RecoveryChangedItem(
            factor_code=change.factor_code,
            title=_FACTOR_TITLE[change.factor_code],
            description=change.fact_text,
        )
        for change in request.changes
    ]
    if changed_items:
        headline = f"{changed_items[0].title} 생활 리듬을 함께 살펴봤어요."
        summary = " ".join(
            item.description for item in changed_items[:2]
        )
    else:
        headline = "최근 생활 리듬을 차분히 점검해 봤어요."
        summary = "두드러진 위험 변화보다 현재 리듬을 유지하는 데 초점을 맞췄어요."
    weekly_observation = (
        f"최근 7일 중 {request.period.record_days}일의 기록을 바탕으로 "
        "평소 기준과 비교했어요."
    )
    if request.is_provisional:
        weekly_observation += " 일부 신호가 부족해 결과는 잠정적이에요."
    return RecoveryReportCopy(
        headline=headline,
        summary=summary,
        weekly_observation=weekly_observation,
        changed_items=changed_items,
        recommendation_intro="이번 주에는 부담이 적은 한 가지부터 시작해 보세요.",
        recommendation_descriptions=[
            RecoveryRecommendationDescription(
                action_id=action.id,
                reason=_ACTION_REASON[action.id],
            )
            for action in request.selected_actions
        ],
    )


async def generate_recovery_report_copy(
    prepared: PreparedRecoveryReport,
    *,
    ai_client: AIServiceClient,
) -> tuple[
    RecoveryReportCopy,
    ReportGenerationStatus,
    str | None,
]:
    try:
        response = await ai_client.generate_recovery_report(prepared.request)
        response.validate_against(prepared.request)
        return (
            RecoveryReportCopy.model_validate(
                response.model_dump(
                    exclude={"model_name", "prompt_version"}
                )
            ),
            ReportGenerationStatus.LLM_GENERATED,
            response.model_name,
        )
    except (AIServiceError, ValidationError, ValueError) as exc:
        LOGGER.warning(
            "Recovery report generation fell back to templates error=%s",
            type(exc).__name__,
        )
        return (
            build_template_fallback(prepared.request),
            ReportGenerationStatus.TEMPLATE_FALLBACK,
            None,
        )


def store_prepared_recovery_report(
    session: Session,
    *,
    prepared: PreparedRecoveryReport,
    content: RecoveryReportCopy,
    generation_status: ReportGenerationStatus,
    model_name: str | None,
) -> RecoveryReport:
    if session.in_transaction():
        raise RuntimeError(
            "recovery report write phase requires a fresh transaction"
        )
    evaluation, reloaded_request, input_snapshot = _load_prepared(
        session,
        user_id=prepared.user_id,
        risk_evaluation_id=prepared.risk_evaluation_id,
        for_update=True,
    )
    reloaded_request = reloaded_request.model_copy(
        update={"selected_actions": prepared.request.selected_actions}
    )
    if (
        reloaded_request != prepared.request
        or input_snapshot != prepared.input_snapshot
    ):
        raise RecoveryReportInputsChangedError(
            "recovery report inputs changed before persistence"
        )
    return create_recovery_report(
        session,
        user_id=prepared.user_id,
        risk_evaluation=evaluation,
        request=prepared.request,
        content=content,
        generation_status=generation_status,
        model_name=model_name,
        disclaimer=REPORT_DISCLAIMER,
    )


async def select_recovery_actions_for_report(
    prepared: PreparedRecoveryReport,
    *,
    ai_client: AIServiceClient,
) -> PreparedRecoveryReport:
    """Select up to three fixed candidates, always falling back safely."""
    request = prepared.request
    fallback = select_recovery_actions(
        [change.factor_code for change in request.changes],
        stage2_signals=request.stage2_signal_drivers,
    )
    # A provisional/insufficient report is the new-user path: deterministic
    # defaults avoid an unnecessary LLM call and work with sparse data.
    if request.is_provisional or request.data_quality == "insufficient":
        selected = select_default_recovery_actions()
    else:
        try:
            response = await ai_client.select_recovery_actions(
                RecoveryActionSelectionRequest(
                    candidates=recovery_candidate_pool(),
                    stage2_signals=request.stage2_signal_drivers,
                    factor_codes=[
                        change.factor_code.value for change in request.changes
                    ],
                    risk_level=request.risk_level,
                    risk_score=request.risk_score,
                    data_quality=request.data_quality,
                    is_provisional=request.is_provisional,
                )
            )
            selected = actions_from_candidate_ids(response.ids)
        except Exception:
            LOGGER.warning(
                "Recovery action selection fell back to defaults",
                exc_info=True,
            )
            selected = fallback
    return PreparedRecoveryReport(
        user_id=prepared.user_id,
        risk_evaluation_id=prepared.risk_evaluation_id,
        request=request.model_copy(update={"selected_actions": selected}),
        input_snapshot=prepared.input_snapshot,
    )


__all__ = [
    "REPORT_DISCLAIMER",
    "PreparedRecoveryReport",
    "RecoveryReportInputUnavailableError",
    "RecoveryReportInputsChangedError",
    "RiskEvaluationNotFoundError",
    "build_template_fallback",
    "generate_recovery_report_copy",
    "select_recovery_actions_for_report",
    "prepare_recovery_report",
    "store_prepared_recovery_report",
]
