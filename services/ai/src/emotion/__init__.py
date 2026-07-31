"""Public emotion inference interfaces."""

from .base import (
    EmotionAnalyzer,
    EmotionAnalyzerError,
    EmptyDiaryTextError,
    ModelArtifactNotConfiguredError,
    ModelArtifactNotFoundError,
    ModelLoadError,
    ModelNotLoadedError,
    ModelNotReadyError,
    ModelNotTrainedError,
    OptionalDependencyError,
    OptionalDependencyMissingError,
    PredictionError,
    PredictionExecutionError,
    PredictionOutputError,
)
from .coarse_settings import CoarseEmotionSettings, NeutralGateSettings
from .coarse_transformer import CoarseTransformerEmotionAnalyzer
from .gated_analyzer import NeutralGatedEmotionAnalyzer
from .neutral_gate import NeutralGateAnalyzer, NeutralGateResult
from .tfidf_analyzer import TFIDFEmotionAnalyzer, TfidfEmotionAnalyzer
from .transformer_analyzer import TransformerEmotionAnalyzer

__all__ = [
    "CoarseEmotionSettings",
    "CoarseTransformerEmotionAnalyzer",
    "EmotionAnalyzer",
    "EmotionAnalyzerError",
    "EmptyDiaryTextError",
    "ModelArtifactNotConfiguredError",
    "ModelArtifactNotFoundError",
    "ModelLoadError",
    "ModelNotLoadedError",
    "ModelNotReadyError",
    "ModelNotTrainedError",
    "NeutralGateAnalyzer",
    "NeutralGateResult",
    "NeutralGateSettings",
    "NeutralGatedEmotionAnalyzer",
    "OptionalDependencyError",
    "OptionalDependencyMissingError",
    "PredictionError",
    "PredictionExecutionError",
    "PredictionOutputError",
    "TFIDFEmotionAnalyzer",
    "TfidfEmotionAnalyzer",
    "TransformerEmotionAnalyzer",
]
