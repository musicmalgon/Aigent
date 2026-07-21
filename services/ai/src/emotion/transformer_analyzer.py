"""Offline-only adapter for a future Transformer emotion classifier."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..schemas import EmotionAnalysis
from .base import (
    EmotionAnalyzer,
    ModelArtifactNotConfiguredError,
    ModelArtifactNotFoundError,
    ModelLoadError,
    ModelNotLoadedError,
    OptionalDependencyMissingError,
    PredictionExecutionError,
    PredictionOutputError,
    coerce_emotion_label,
    validate_diary_text,
    validate_model_metadata,
)


class TransformerEmotionAnalyzer(EmotionAnalyzer):
    """Load an already-prepared local Transformer model without downloads."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        *,
        model_name: str,
        model_version: str,
    ) -> None:
        self.model_path = Path(model_path) if model_path is not None else None
        self.model_name, self.model_version = validate_model_metadata(
            model_name,
            model_version,
        )
        self._classifier: Any | None = None

    @property
    def is_loaded(self) -> bool:
        """Whether the local text-classification pipeline is ready."""

        return self._classifier is not None

    def _local_model_path(self) -> Path:
        if self.model_path is None:
            raise ModelArtifactNotConfiguredError(
                "Transformer model_path must reference a prepared local "
                "directory; no model is downloaded automatically"
            )
        if not self.model_path.is_dir():
            raise ModelArtifactNotFoundError(
                f"Transformer local model directory not found: {self.model_path}; "
                "remote model identifiers and automatic downloads are disabled"
            )
        return self.model_path

    def load(self) -> None:
        """Build a local-only Transformers pipeline via a lazy import."""

        model_path = self._local_model_path()
        try:
            transformers = importlib.import_module("transformers")
        except ImportError as exc:
            raise OptionalDependencyMissingError(
                "Transformer inference requires the optional 'transformers' "
                "dependency and the supported local PyTorch runtime backend"
            ) from exc

        try:
            tokenizer = transformers.AutoTokenizer.from_pretrained(
                model_path,
                local_files_only=True,
            )
            model = transformers.AutoModelForSequenceClassification.from_pretrained(
                model_path,
                local_files_only=True,
            )
            classifier = transformers.pipeline(
                "text-classification",
                model=model,
                tokenizer=tokenizer,
            )
        except ImportError as exc:
            raise OptionalDependencyMissingError(
                "Transformer inference dependencies are incomplete; install "
                "'transformers' with the supported local PyTorch runtime backend"
            ) from exc
        except Exception as exc:
            raise ModelLoadError(
                "Transformer artifacts could not be loaded from the configured "
                "local directory; no remote download was attempted"
            ) from exc

        self._classifier = classifier

    def predict(self, text: str) -> EmotionAnalysis:
        """Return the common schema from one local pipeline prediction."""

        normalized_text = validate_diary_text(text)
        self._local_model_path()
        if self._classifier is None:
            raise ModelNotLoadedError(
                "Transformer model is configured but not loaded; call load() "
                "before predict()"
            )

        try:
            outputs = self._classifier(normalized_text)
        except Exception as exc:
            raise PredictionExecutionError(
                "Transformer text-classification inference failed"
            ) from exc

        try:
            output = outputs[0]
            if not isinstance(output, Mapping):
                raise TypeError("first pipeline output is not a mapping")
            raw_label = output["label"]
            confidence = float(output["score"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise PredictionOutputError(
                "Transformer pipeline must return [{'label': ..., 'score': ...}]"
            ) from exc

        if not 0.0 <= confidence <= 1.0:
            raise PredictionOutputError(
                "Transformer model confidence must be between 0 and 1"
            )

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


__all__ = ["TransformerEmotionAnalyzer"]
