"""Local joblib adapter for a future TF-IDF emotion classifier.

This module only loads trusted, pre-existing artifacts.  It never trains or
downloads a model.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from ..schemas import EmotionAnalysis
from .base import (
    EmotionAnalyzer,
    ModelArtifactNotConfiguredError,
    ModelArtifactNotFoundError,
    ModelLoadError,
    ModelNotLoadedError,
    ModelNotTrainedError,
    OptionalDependencyMissingError,
    PredictionExecutionError,
    PredictionOutputError,
    coerce_emotion_label,
    validate_diary_text,
    validate_model_metadata,
)


class TfidfEmotionAnalyzer(EmotionAnalyzer):
    """Adapt local scikit-learn-style artifacts to ``EmotionAnalysis``."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        vectorizer_path: str | Path | None = None,
        *,
        model_name: str,
        model_version: str,
    ) -> None:
        self.model_path = Path(model_path) if model_path is not None else None
        self.vectorizer_path = (
            Path(vectorizer_path) if vectorizer_path is not None else None
        )
        self.model_name, self.model_version = validate_model_metadata(
            model_name,
            model_version,
        )
        self._model: Any | None = None
        self._vectorizer: Any | None = None

    @property
    def is_loaded(self) -> bool:
        """Whether both in-memory inference artifacts are ready."""

        return self._model is not None and self._vectorizer is not None

    def _artifact_paths(self) -> tuple[Path, Path]:
        if self.model_path is None or self.vectorizer_path is None:
            raise ModelArtifactNotConfiguredError(
                "TF-IDF model_path and vectorizer_path must both be configured; "
                "training and artifact discovery are not performed automatically"
            )

        missing_paths = [
            path
            for path in (self.model_path, self.vectorizer_path)
            if not path.is_file()
        ]
        if missing_paths:
            rendered_paths = ", ".join(str(path) for path in missing_paths)
            raise ModelArtifactNotFoundError(
                "TF-IDF artifact file(s) not found: "
                f"{rendered_paths}; no model is downloaded or trained automatically"
            )
        return self.model_path, self.vectorizer_path

    def load(self) -> None:
        """Load trusted artifacts with the configured joblib/sklearn runtime."""

        model_path, vectorizer_path = self._artifact_paths()
        try:
            joblib = importlib.import_module("joblib")
        except ImportError as exc:
            raise OptionalDependencyMissingError(
                "TF-IDF artifact loading requires compatible 'joblib' and "
                "'scikit-learn' dependencies in the AI inference environment"
            ) from exc

        try:
            model = joblib.load(model_path)
            vectorizer = joblib.load(vectorizer_path)
        except ImportError as exc:
            raise OptionalDependencyMissingError(
                "TF-IDF artifact dependencies are incomplete; install versions "
                "compatible with the trusted artifact manifest"
            ) from exc
        except Exception as exc:
            raise ModelLoadError(
                "TF-IDF artifacts could not be loaded. Verify that both files "
                "are trusted, compatible joblib artifacts."
            ) from exc

        self._model = model
        self._vectorizer = vectorizer

    def predict(self, text: str) -> EmotionAnalysis:
        """Return the shared schema without training or estimating new rules."""

        normalized_text = validate_diary_text(text)
        self._artifact_paths()
        if not self.is_loaded:
            raise ModelNotLoadedError(
                "TF-IDF artifacts are configured but not loaded; call load() "
                "before predict()"
            )

        model = self._model
        vectorizer = self._vectorizer
        if model is None or vectorizer is None:  # pragma: no cover - type guard
            raise ModelNotLoadedError("TF-IDF model and vectorizer are not loaded")
        if not hasattr(model, "classes_"):
            raise ModelNotTrainedError(
                "loaded TF-IDF model has no classes_; provide a fitted "
                "classifier artifact"
            )

        try:
            features = vectorizer.transform([normalized_text])
            predictions = model.predict(features)
        except Exception as exc:
            if type(exc).__name__ == "NotFittedError":
                raise ModelNotTrainedError(
                    "loaded TF-IDF model or vectorizer is not fitted"
                ) from exc
            raise PredictionExecutionError(
                "TF-IDF vectorization or classifier prediction failed"
            ) from exc

        try:
            raw_label = predictions[0]
        except (IndexError, KeyError, TypeError) as exc:
            raise PredictionOutputError(
                "TF-IDF model.predict() must return one label per input"
            ) from exc

        confidence = self._prediction_confidence(model, features, raw_label)
        return EmotionAnalysis(
            primary_emotion=coerce_emotion_label(raw_label),
            secondary_signals=[],
            confidence=confidence,
            cause_tags=[],
            sleep_related=None,
            workload_related=None,
            model_name=self.model_name,
            model_version=self.model_version,
        )

    @staticmethod
    def _prediction_confidence(
        model: Any,
        features: Any,
        raw_label: object,
    ) -> float:
        """Read classifier probability without inventing a confidence value."""

        if not hasattr(model, "predict_proba"):
            raise PredictionOutputError(
                "TF-IDF model must expose predict_proba() and classes_ to "
                "populate EmotionAnalysis.confidence without estimation"
            )

        try:
            probabilities = model.predict_proba(features)
        except Exception as exc:
            if type(exc).__name__ == "NotFittedError":
                raise ModelNotTrainedError("loaded TF-IDF model is not fitted") from exc
            raise PredictionExecutionError(
                "TF-IDF classifier predict_proba() failed"
            ) from exc

        try:
            classes = list(model.classes_)
            label_index = classes.index(raw_label)
            confidence = float(probabilities[0][label_index])
        except (IndexError, TypeError, ValueError) as exc:
            raise PredictionOutputError(
                "TF-IDF predict_proba() output does not align with model.classes_"
            ) from exc

        if not 0.0 <= confidence <= 1.0:
            raise PredictionOutputError(
                "TF-IDF model confidence must be between 0 and 1"
            )
        return confidence


# Compatibility spelling for callers that preserve the TF-IDF acronym.
TFIDFEmotionAnalyzer = TfidfEmotionAnalyzer


__all__ = ["TFIDFEmotionAnalyzer", "TfidfEmotionAnalyzer"]
