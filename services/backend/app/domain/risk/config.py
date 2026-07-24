"""Immutable policy configuration for burnout risk rules v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import FactorCode, RiskCategory, RiskLevel


@dataclass(frozen=True)
class RiskEngineConfig:
    """Versioned product policy, not clinical thresholds."""

    engine_version: Literal["burnout-risk-rules-v1"] = "burnout-risk-rules-v1"
    category_weights: tuple[tuple[RiskCategory, float], ...] = (
        (RiskCategory.SLEEP, 0.25),
        (RiskCategory.WORKLOAD, 0.20),
        (RiskCategory.RECOVERY, 0.20),
        (RiskCategory.EMOTION, 0.20),
        (RiskCategory.SUBJECTIVE, 0.15),
    )
    level_thresholds: tuple[tuple[RiskLevel, float], ...] = (
        (RiskLevel.LOW, 0.0),
        (RiskLevel.MODERATE, 25.0),
        (RiskLevel.HIGH, 50.0),
        (RiskLevel.VERY_HIGH, 75.0),
    )
    minimum_baseline_days: int = 7
    recommended_baseline_days: tuple[int, int] = (14, 28)
    minimum_available_signals: int = 4
    minimum_available_categories: int = 3
    adverse_change_points: tuple[tuple[float, float], ...] = (
        (0.0, 0.0),
        (0.10, 0.20),
        (0.25, 0.60),
        (0.40, 0.90),
    )
    extreme_adverse_change: float = 0.40
    emotion_change_points: tuple[tuple[float, float], ...] = (
        (0.0, 0.0),
        (0.05, 0.20),
        (0.15, 0.60),
        (0.30, 1.00),
    )
    absolute_emotion_points: tuple[tuple[float, float], ...] = (
        (0.50, 0.0),
        (0.65, 0.30),
        (0.80, 0.70),
        (1.00, 1.00),
    )
    workload_inner_weights: tuple[float, float] = (0.65, 0.35)
    recovery_inner_weights: tuple[float, float] = (0.80, 0.20)
    subjective_inner_weights: tuple[float, float] = (0.55, 0.45)
    sleep_fallback_reference_minutes: float = 420.0
    workload_fallback_reference_minutes: float = 480.0
    schedule_fallback_reference_count: float = 4.0
    rest_fallback_reference_minutes: float = 60.0
    exercise_fallback_reference_minutes: float = 20.0
    general_fallback_severity_cap: float = 0.60
    exercise_severity_cap: float = 0.30
    exercise_fallback_severity_cap: float = 0.30
    emotion_fallback_severity_cap: float = 0.50
    subjective_severity_cap: float = 0.45
    subjective_fallback_severity_cap: float = 0.45
    subjective_increase_for_full_severity: float = 5.0
    confidence_floor: float = 0.50
    missing_confidence_multiplier: float = 0.75
    uncertainty_multiplier: float = 0.75
    provisional_score_cap: float = 74.99
    factor_codes: tuple[FactorCode, ...] = tuple(FactorCode)

    def __post_init__(self) -> None:
        if self.engine_version != "burnout-risk-rules-v1":
            raise ValueError("v1 policy requires the v1 engine version")
        if abs(sum(weight for _, weight in self.category_weights) - 1.0) > 1e-12:
            raise ValueError("category weights must sum to 1.0")
        if self.minimum_baseline_days < 1:
            raise ValueError("minimum baseline days must be positive")
        if self.minimum_available_categories < 1:
            raise ValueError("minimum available categories must be positive")
        if not 0 <= self.provisional_score_cap < 75:
            raise ValueError("provisional score cap must remain below very_high")
        if tuple(level for level, _ in self.level_thresholds) != tuple(RiskLevel):
            raise ValueError("level thresholds must define every risk level in order")
        if self.factor_codes != tuple(FactorCode):
            raise ValueError("factor code policy must enumerate every factor code")


DEFAULT_CONFIG = RiskEngineConfig()


__all__ = ["DEFAULT_CONFIG", "RiskEngineConfig"]
