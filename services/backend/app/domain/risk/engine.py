"""Deterministic and explainable burnout risk rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .config import DEFAULT_CONFIG, RiskEngineConfig
from .models import (
    BaselineStatus,
    BurnoutRiskEvaluationRequest,
    BurnoutRiskEvaluationResponse,
    CurrentRiskSignals,
    DataQuality,
    FactorCategory,
    FactorCode,
    FactorKind,
    PersonalBaseline,
    RiskCategory,
    RiskFactor,
    RiskLevel,
    RiskSummary,
)


@dataclass(frozen=True)
class _SignalFactor:
    code: FactorCode
    category: RiskCategory
    observed_value: float
    baseline_value: float | None
    change_percent: float | None
    severity: float
    inner_weight: float
    message_key: str


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _interpolate(
    value: float,
    points: tuple[tuple[float, float], ...],
) -> float:
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            ratio = (value - x0) / (x1 - x0)
            return _clamp(y0 + ratio * (y1 - y0))
    return _clamp(points[-1][1])


def _adverse_change_severity(
    adverse_fraction: float,
    config: RiskEngineConfig,
) -> float:
    adverse_fraction = max(0.0, adverse_fraction)
    if adverse_fraction >= config.extreme_adverse_change:
        return 1.0
    return _interpolate(adverse_fraction, config.adverse_change_points)


def _relative_change(current: float, baseline: float) -> float | None:
    if baseline <= 0:
        return None
    return (current - baseline) / baseline


def _baseline_status(
    baseline: PersonalBaseline | None,
    config: RiskEngineConfig,
) -> BaselineStatus:
    if baseline is None:
        return BaselineStatus.MISSING
    if baseline.sample_days < config.minimum_baseline_days:
        return BaselineStatus.INSUFFICIENT
    return BaselineStatus.READY


def _renormalized_weights(
    desired_weights: Iterable[float],
) -> tuple[float, ...]:
    weights = tuple(desired_weights)
    total = sum(weights)
    return tuple(weight / total for weight in weights)


def _comparison_or_fallback(
    *,
    current: float,
    baseline: float | None,
    direction: str,
    fallback_severity: float,
    fallback_cap: float,
    config: RiskEngineConfig,
) -> tuple[float, float | None, bool]:
    if baseline is not None:
        change = _relative_change(current, baseline)
        if change is not None:
            adverse = -change if direction == "decrease" else change
            return _adverse_change_severity(adverse, config), change * 100.0, False
        if direction == "decrease":
            return 0.0, None, False
    return min(fallback_severity, fallback_cap), None, True


def _sleep_factors(
    current: CurrentRiskSignals,
    baseline: PersonalBaseline | None,
    config: RiskEngineConfig,
) -> tuple[list[_SignalFactor], bool]:
    if current.sleep_minutes is None:
        return [], False
    baseline_value = baseline.sleep_minutes if baseline else None
    fallback_fraction = max(
        0.0,
        (config.sleep_fallback_reference_minutes - current.sleep_minutes)
        / config.sleep_fallback_reference_minutes,
    )
    severity, change, used_fallback = _comparison_or_fallback(
        current=current.sleep_minutes,
        baseline=baseline_value,
        direction="decrease",
        fallback_severity=_adverse_change_severity(fallback_fraction, config),
        fallback_cap=config.general_fallback_severity_cap,
        config=config,
    )
    return [
        _SignalFactor(
            code=FactorCode.SLEEP_DECREASE,
            category=RiskCategory.SLEEP,
            observed_value=current.sleep_minutes,
            baseline_value=baseline_value,
            change_percent=change,
            severity=severity,
            inner_weight=1.0,
            message_key="risk.sleep.decreased",
        )
    ], used_fallback


def _workload_factors(
    current: CurrentRiskSignals,
    baseline: PersonalBaseline | None,
    config: RiskEngineConfig,
) -> tuple[list[_SignalFactor], bool]:
    specs = (
        (
            FactorCode.WORKLOAD_INCREASE,
            current.work_or_study_minutes,
            baseline.work_or_study_minutes if baseline else None,
            config.workload_fallback_reference_minutes,
            config.workload_inner_weights[0],
            "risk.workload.increased",
        ),
        (
            FactorCode.SCHEDULE_OVERLOAD,
            float(current.schedule_count) if current.schedule_count is not None else None,
            baseline.schedule_count if baseline else None,
            config.schedule_fallback_reference_count,
            config.workload_inner_weights[1],
            "risk.schedule.increased",
        ),
    )
    present = [spec for spec in specs if spec[1] is not None]
    weights = _renormalized_weights(spec[4] for spec in present)
    factors: list[_SignalFactor] = []
    used_fallback = False
    for weight, (
        code,
        observed,
        baseline_value,
        fallback_reference,
        _,
        message_key,
    ) in zip(weights, present):
        assert observed is not None
        fallback_fraction = max(
            0.0,
            (observed - fallback_reference) / fallback_reference,
        )
        severity, change, fallback = _comparison_or_fallback(
            current=observed,
            baseline=baseline_value,
            direction="increase",
            fallback_severity=_adverse_change_severity(
                fallback_fraction,
                config,
            ),
            fallback_cap=config.general_fallback_severity_cap,
            config=config,
        )
        factors.append(
            _SignalFactor(
                code=code,
                category=RiskCategory.WORKLOAD,
                observed_value=observed,
                baseline_value=baseline_value,
                change_percent=change,
                severity=severity,
                inner_weight=weight,
                message_key=message_key,
            )
        )
        used_fallback = used_fallback or fallback
    return factors, used_fallback


def _recovery_factors(
    current: CurrentRiskSignals,
    baseline: PersonalBaseline | None,
    config: RiskEngineConfig,
) -> tuple[list[_SignalFactor], bool]:
    specs = (
        (
            FactorCode.REST_DECREASE,
            current.rest_minutes,
            baseline.rest_minutes if baseline else None,
            config.rest_fallback_reference_minutes,
            config.recovery_inner_weights[0],
            1.0,
            config.general_fallback_severity_cap,
            "risk.rest.decreased",
        ),
        (
            FactorCode.EXERCISE_DECREASE,
            current.exercise_minutes,
            baseline.exercise_minutes if baseline else None,
            config.exercise_fallback_reference_minutes,
            config.recovery_inner_weights[1],
            config.exercise_severity_cap,
            config.exercise_fallback_severity_cap,
            "risk.exercise.decreased",
        ),
    )
    present = [spec for spec in specs if spec[1] is not None]
    weights = _renormalized_weights(spec[4] for spec in present)
    factors: list[_SignalFactor] = []
    used_fallback = False
    for weight, (
        code,
        observed,
        baseline_value,
        fallback_reference,
        _,
        severity_cap,
        fallback_cap,
        message_key,
    ) in zip(weights, present):
        assert observed is not None
        fallback_fraction = max(
            0.0,
            (fallback_reference - observed) / fallback_reference,
        )
        severity, change, fallback = _comparison_or_fallback(
            current=observed,
            baseline=baseline_value,
            direction="decrease",
            fallback_severity=_adverse_change_severity(
                fallback_fraction,
                config,
            ),
            fallback_cap=fallback_cap,
            config=config,
        )
        severity = min(severity, severity_cap)
        factors.append(
            _SignalFactor(
                code=code,
                category=RiskCategory.RECOVERY,
                observed_value=observed,
                baseline_value=baseline_value,
                change_percent=change,
                severity=severity,
                inner_weight=weight,
                message_key=message_key,
            )
        )
        used_fallback = used_fallback or fallback
    return factors, used_fallback


def _emotion_factors(
    current: CurrentRiskSignals,
    baseline: PersonalBaseline | None,
    config: RiskEngineConfig,
) -> tuple[list[_SignalFactor], bool]:
    if current.emotion_probabilities is None:
        return [], False
    observed = _clamp(current.emotion_probabilities.negative_probability)
    baseline_value = baseline.negative_emotion_probability if baseline else None
    if baseline_value is None:
        raw_severity = min(
            _interpolate(observed, config.absolute_emotion_points),
            config.emotion_fallback_severity_cap,
        )
        change_percent = None
        code = FactorCode.HIGH_NEGATIVE_EMOTION
        message_key = "risk.emotion.negative_high"
        used_fallback = True
    else:
        increase = max(0.0, observed - baseline_value)
        raw_severity = _interpolate(increase, config.emotion_change_points)
        change_percent = increase * 100.0
        code = FactorCode.NEGATIVE_EMOTION_INCREASE
        message_key = "risk.emotion.negative_increased"
        used_fallback = False

    confidence_multiplier = (
        config.missing_confidence_multiplier
        if current.emotion_confidence is None
        else config.confidence_floor
        + (1.0 - config.confidence_floor) * current.emotion_confidence
    )
    uncertainty_multiplier = (
        config.uncertainty_multiplier
        if current.emotion_uncertain is True
        else 1.0
    )
    severity = _clamp(
        raw_severity * confidence_multiplier * uncertainty_multiplier
    )
    return [
        _SignalFactor(
            code=code,
            category=RiskCategory.EMOTION,
            observed_value=observed,
            baseline_value=baseline_value,
            change_percent=change_percent,
            severity=severity,
            inner_weight=1.0,
            message_key=message_key,
        )
    ], used_fallback


def _subjective_factors(
    current: CurrentRiskSignals,
    baseline: PersonalBaseline | None,
    config: RiskEngineConfig,
) -> tuple[list[_SignalFactor], bool]:
    specs = (
        (
            FactorCode.SUBJECTIVE_STRESS,
            current.subjective_stress,
            baseline.subjective_stress if baseline else None,
            config.subjective_inner_weights[0],
            "risk.subjective.stress",
        ),
        (
            FactorCode.SUBJECTIVE_FATIGUE,
            current.subjective_fatigue,
            baseline.subjective_fatigue if baseline else None,
            config.subjective_inner_weights[1],
            "risk.subjective.fatigue",
        ),
    )
    present = [spec for spec in specs if spec[1] is not None]
    weights = _renormalized_weights(spec[3] for spec in present)
    factors: list[_SignalFactor] = []
    used_fallback = False
    for weight, (code, observed, baseline_value, _, message_key) in zip(
        weights,
        present,
    ):
        assert observed is not None
        if baseline_value is None:
            severity = min(
                observed / 10.0,
                config.subjective_fallback_severity_cap,
            )
            change_percent = None
            fallback = True
        else:
            increase = max(0.0, observed - baseline_value)
            severity = min(
                _clamp(increase / config.subjective_increase_for_full_severity),
                config.subjective_severity_cap,
            )
            change_percent = increase * 10.0
            fallback = False
        factors.append(
            _SignalFactor(
                code=code,
                category=RiskCategory.SUBJECTIVE,
                observed_value=observed,
                baseline_value=baseline_value,
                change_percent=change_percent,
                severity=severity,
                inner_weight=weight,
                message_key=message_key,
            )
        )
        used_fallback = used_fallback or fallback
    return factors, used_fallback


def _signal_counts(current: CurrentRiskSignals) -> tuple[int, int]:
    available = sum(
        (
            current.sleep_minutes is not None,
            current.work_or_study_minutes is not None,
            current.rest_minutes is not None,
            current.exercise_minutes is not None,
            current.schedule_count is not None,
            current.emotion_probabilities is not None,
            (
                current.subjective_stress is not None
                or current.subjective_fatigue is not None
            ),
        )
    )
    return available, 7 - available


def risk_level_for_score(
    score: float,
    config: RiskEngineConfig = DEFAULT_CONFIG,
) -> RiskLevel:
    """Return the configured level after clamping a score to 0..100."""

    score = max(0.0, min(100.0, score))
    selected = RiskLevel.LOW
    for level, threshold in config.level_thresholds:
        if score >= threshold:
            selected = level
    return selected


class BurnoutRiskEngine:
    """Evaluate versioned rules without I/O, persistence, or model calls."""

    def __init__(self, config: RiskEngineConfig = DEFAULT_CONFIG) -> None:
        self._config = config

    @property
    def config(self) -> RiskEngineConfig:
        return self._config

    def evaluate(
        self,
        request: BurnoutRiskEvaluationRequest | None = None,
        *,
        current: CurrentRiskSignals | None = None,
        baseline: PersonalBaseline | None = None,
    ) -> BurnoutRiskEvaluationResponse:
        if request is not None and (current is not None or baseline is not None):
            raise ValueError("provide either request or current/baseline")
        if request is None:
            if current is None:
                raise ValueError("current signals are required")
            request = BurnoutRiskEvaluationRequest(
                current=current,
                baseline=baseline,
            )
        return self._evaluate_request(request)

    def _evaluate_request(
        self,
        request: BurnoutRiskEvaluationRequest,
    ) -> BurnoutRiskEvaluationResponse:
        config = self._config
        status = _baseline_status(request.baseline, config)
        comparison_baseline = (
            request.baseline if status is BaselineStatus.READY else None
        )
        builders: tuple[
            tuple[
                RiskCategory,
                Callable[[], tuple[list[_SignalFactor], bool]],
            ],
            ...,
        ] = (
            (
                RiskCategory.SLEEP,
                lambda: _sleep_factors(
                    request.current,
                    comparison_baseline,
                    config,
                ),
            ),
            (
                RiskCategory.WORKLOAD,
                lambda: _workload_factors(
                    request.current,
                    comparison_baseline,
                    config,
                ),
            ),
            (
                RiskCategory.RECOVERY,
                lambda: _recovery_factors(
                    request.current,
                    comparison_baseline,
                    config,
                ),
            ),
            (
                RiskCategory.EMOTION,
                lambda: _emotion_factors(
                    request.current,
                    comparison_baseline,
                    config,
                ),
            ),
            (
                RiskCategory.SUBJECTIVE,
                lambda: _subjective_factors(
                    request.current,
                    comparison_baseline,
                    config,
                ),
            ),
        )

        category_factors: dict[RiskCategory, list[_SignalFactor]] = {}
        used_fallback = False
        for category, builder in builders:
            factors, fallback = builder()
            if factors:
                category_factors[category] = factors
            used_fallback = used_fallback or fallback

        available_signals, missing_signals = _signal_counts(request.current)
        available_categories = len(category_factors)
        quality = (
            DataQuality.SUFFICIENT
            if (
                available_signals >= config.minimum_available_signals
                and available_categories >= config.minimum_available_categories
            )
            else DataQuality.INSUFFICIENT
        )
        is_provisional = (
            status is not BaselineStatus.READY
            or used_fallback
            or quality is DataQuality.INSUFFICIENT
        )

        configured_weights = dict(config.category_weights)
        available_weight = sum(
            configured_weights[category] for category in category_factors
        )
        normalized_category_weights = (
            {
                category: configured_weights[category] / available_weight
                for category in category_factors
            }
            if available_weight
            else {}
        )

        category_scores: dict[RiskCategory, float] = {}
        contributions: list[tuple[_SignalFactor, float, float]] = []
        for category, factors in category_factors.items():
            category_severity = _clamp(
                sum(item.severity * item.inner_weight for item in factors)
            )
            category_scores[category] = round(category_severity * 100.0, 2)
            category_weight = normalized_category_weights[category]
            for item in factors:
                effective_weight = item.inner_weight * category_weight
                contribution = item.severity * effective_weight * 100.0
                if contribution > 0:
                    contributions.append(
                        (item, effective_weight, contribution)
                    )

        raw_score = sum(item[2] for item in contributions)
        provisional_scale = (
            config.provisional_score_cap / raw_score
            if is_provisional and raw_score > config.provisional_score_cap
            else 1.0
        )
        risk_factors = [
            RiskFactor(
                code=item.code,
                category=FactorCategory(item.category.value),
                kind=FactorKind.RISK,
                severity=round(_clamp(item.severity), 6),
                weight=round(effective_weight * provisional_scale, 6),
                contribution=round(contribution * provisional_scale, 4),
                observed_value=round(item.observed_value, 4),
                baseline_value=(
                    round(item.baseline_value, 4)
                    if item.baseline_value is not None
                    else None
                ),
                change_percent=(
                    round(item.change_percent, 4)
                    if item.change_percent is not None
                    else None
                ),
                message_key=item.message_key,
            )
            for item, effective_weight, contribution in contributions
        ]

        informational_factors: list[RiskFactor] = []
        if status is not BaselineStatus.READY:
            informational_factors.append(
                RiskFactor(
                    code=FactorCode.INSUFFICIENT_BASELINE,
                    category=FactorCategory.DATA_QUALITY,
                    kind=FactorKind.INFORMATIONAL,
                    severity=0,
                    weight=0,
                    contribution=0,
                    observed_value=(
                        float(request.baseline.sample_days)
                        if request.baseline is not None
                        else None
                    ),
                    baseline_value=float(config.minimum_baseline_days),
                    change_percent=None,
                    message_key="risk.data.baseline_insufficient",
                )
            )
        if quality is DataQuality.INSUFFICIENT:
            informational_factors.append(
                RiskFactor(
                    code=FactorCode.INSUFFICIENT_DATA,
                    category=FactorCategory.DATA_QUALITY,
                    kind=FactorKind.INFORMATIONAL,
                    severity=0,
                    weight=0,
                    contribution=0,
                    observed_value=float(available_signals),
                    baseline_value=float(config.minimum_available_signals),
                    change_percent=None,
                    message_key="risk.data.signals_insufficient",
                )
            )

        response_factors = risk_factors + informational_factors
        response_factors.sort(
            key=lambda item: (-item.contribution, item.code.value)
        )
        score = round(sum(item.contribution for item in risk_factors), 2)
        top_factor_codes = [
            item.code
            for item in response_factors
            if item.kind is FactorKind.RISK
        ][:3]

        return BurnoutRiskEvaluationResponse(
            score=score,
            level=risk_level_for_score(score, config),
            is_provisional=is_provisional,
            baseline_status=status,
            data_quality=quality,
            category_scores=category_scores,
            factors=response_factors,
            summary=RiskSummary(
                top_factor_codes=top_factor_codes,
                available_signal_count=available_signals,
                missing_signal_count=missing_signals,
                available_category_count=available_categories,
                missing_category_count=5 - available_categories,
            ),
            engine_version=config.engine_version,
        )


def evaluate_burnout_risk(
    request: BurnoutRiskEvaluationRequest,
    config: RiskEngineConfig = DEFAULT_CONFIG,
) -> BurnoutRiskEvaluationResponse:
    """Functional interface for callers that do not need an engine instance."""

    return BurnoutRiskEngine(config).evaluate(request)


__all__ = [
    "BurnoutRiskEngine",
    "evaluate_burnout_risk",
    "risk_level_for_score",
]
