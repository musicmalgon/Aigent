"""Explainable, side-effect-free burnout risk rules."""

from .config import DEFAULT_CONFIG, RiskEngineConfig
from .engine import BurnoutRiskEngine, evaluate_burnout_risk, risk_level_for_score
from .models import (
    BaselineStatus,
    BurnoutRiskEvaluationRequest,
    BurnoutRiskEvaluationResponse,
    CurrentRiskSignals,
    DataQuality,
    EmotionProbabilities,
    FactorCategory,
    FactorCode,
    FactorKind,
    PersonalBaseline,
    RiskCategory,
    RiskFactor,
    RiskLevel,
    RiskSummary,
)

__all__ = [
    "BaselineStatus",
    "BurnoutRiskEngine",
    "BurnoutRiskEvaluationRequest",
    "BurnoutRiskEvaluationResponse",
    "CurrentRiskSignals",
    "DEFAULT_CONFIG",
    "DataQuality",
    "EmotionProbabilities",
    "FactorCategory",
    "FactorCode",
    "FactorKind",
    "PersonalBaseline",
    "RiskCategory",
    "RiskEngineConfig",
    "RiskFactor",
    "RiskLevel",
    "RiskSummary",
    "evaluate_burnout_risk",
    "risk_level_for_score",
]
