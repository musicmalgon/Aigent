"""Common interface and errors for emotion analyzers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas import EmotionAnalysis, EmotionLabel


class EmotionAnalyzerError(RuntimeError):
    """Base error for failures raised by an emotion analyzer."""


class EmptyDiaryTextError(ValueError):
    """Raised when an analyzer receives an empty diary entry."""


class ModelNotReadyError(EmotionAnalyzerError):
    """Base error for an analyzer whose local artifacts are not ready."""


class ModelArtifactNotConfiguredError(ModelNotReadyError):
    """Raised when required local artifact paths were not configured."""


class ModelArtifactNotFoundError(ModelNotReadyError, FileNotFoundError):
    """Raised when a configured local artifact does not exist."""


class ModelNotLoadedError(ModelNotReadyError):
    """Raised when artifacts exist but have not been explicitly loaded."""


class ModelNotTrainedError(ModelNotReadyError):
    """Raised when a loaded artifact has not been fitted for inference."""


class ModelLoadError(ModelNotReadyError):
    """Raised when configured local artifacts cannot be loaded."""


class OptionalDependencyError(ModelNotReadyError, ImportError):
    """Backward-compatible base for optional dependency failures."""


class OptionalDependencyMissingError(OptionalDependencyError):
    """Raised when an inference dependency is absent or incomplete."""


class PredictionError(EmotionAnalyzerError):
    """Base error for failures during model inference."""


class PredictionExecutionError(PredictionError):
    """Raised when a loaded model fails while performing inference."""


class PredictionOutputError(PredictionError):
    """Raised when a loaded model does not satisfy the output contract."""


def validate_diary_text(text: str) -> str:
    """Return stripped diary text or raise a clear input error."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized_text = text.strip()
    if not normalized_text:
        raise EmptyDiaryTextError("text must not be empty or whitespace-only")
    return normalized_text


def coerce_emotion_label(raw_label: object) -> EmotionLabel:
    """Convert a model label to the public four-label contract."""

    label_value = getattr(raw_label, "value", raw_label)
    try:
        return EmotionLabel(str(label_value).lower())
    except ValueError as exc:
        allowed = ", ".join(label.value for label in EmotionLabel)
        raise PredictionOutputError(
            f"model returned unsupported emotion label {label_value!r}; "
            f"expected one of: {allowed}"
        ) from exc


def validate_model_metadata(model_name: str, model_version: str) -> tuple[str, str]:
    """Validate explicit, non-empty model identity used in public results."""

    if not isinstance(model_name, str):
        raise TypeError("model_name must be a string")
    if not isinstance(model_version, str):
        raise TypeError("model_version must be a string")

    normalized_name = model_name.strip()
    normalized_version = model_version.strip()
    if not normalized_name:
        raise ValueError("model_name must not be empty or whitespace-only")
    if not normalized_version:
        raise ValueError("model_version must not be empty or whitespace-only")
    return normalized_name, normalized_version


class EmotionAnalyzer(ABC):
    """Model-independent diary emotion analysis interface."""

    @abstractmethod
    def predict(self, text: str) -> EmotionAnalysis:
        """Analyze one non-empty diary entry."""


__all__ = [
    "EmotionAnalyzer",
    "EmotionAnalyzerError",
    "EmptyDiaryTextError",
    "ModelArtifactNotConfiguredError",
    "ModelArtifactNotFoundError",
    "ModelLoadError",
    "ModelNotLoadedError",
    "ModelNotReadyError",
    "ModelNotTrainedError",
    "OptionalDependencyError",
    "OptionalDependencyMissingError",
    "PredictionError",
    "PredictionExecutionError",
    "PredictionOutputError",
]
