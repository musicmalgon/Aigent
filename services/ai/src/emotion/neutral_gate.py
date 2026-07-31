"""Binary KLUE-RoBERTa gate that separates neutral from emotional diaries."""

from __future__ import annotations

import importlib
import json
import math
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..remind_ai.data.transformer_dataset import transformer_inference_text
from ..schemas import CoarseEmotionInput, NeutralGateDecision
from .base import (
    ModelArtifactNotConfiguredError,
    ModelArtifactNotFoundError,
    ModelLoadError,
    ModelNotLoadedError,
    OptionalDependencyMissingError,
    PredictionExecutionError,
    PredictionOutputError,
)
from .coarse_transformer import select_inference_device

NEUTRAL_GATE_LABELS = ("neutral", "emotional")
NEUTRAL_GATE_LABEL_TO_ID = {
    label: index for index, label in enumerate(NEUTRAL_GATE_LABELS)
}
MODEL_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")


@dataclass(frozen=True, slots=True)
class NeutralGateResult:
    decision: NeutralGateDecision
    neutral_score: float
    emotional_score: float
    threshold: float
    model_version: str
    latency_ms: float


@dataclass(frozen=True, slots=True)
class NeutralGateArtifact:
    model_dir: Path
    tokenizer_dir: Path
    threshold: float
    model_version: str


def _has_model(path: Path) -> bool:
    return (path / "config.json").is_file() and any(
        (path / filename).is_file() for filename in MODEL_WEIGHT_FILES
    )


def _has_tokenizer(path: Path) -> bool:
    return (path / "tokenizer.json").is_file() or (path / "vocab.txt").is_file()


def _load_json_object(path: Path, kind: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelArtifactNotFoundError(f"neutral gate {kind} is unavailable") from exc
    if not isinstance(payload, Mapping):
        raise ModelArtifactNotFoundError(f"neutral gate {kind} is invalid")
    return payload


def resolve_neutral_gate_artifact(
    artifact_dir: Path | None,
    *,
    threshold_override: float | None = None,
    model_version_override: str | None = None,
) -> NeutralGateArtifact:
    if artifact_dir is None:
        raise ModelArtifactNotConfiguredError(
            "configure EMOTION_NEUTRAL_GATE_ARTIFACT_DIR"
        )
    if not artifact_dir.is_dir():
        raise ModelArtifactNotFoundError(
            "neutral gate artifact directory was not found"
        )
    model_dir = artifact_dir / "model"
    tokenizer_dir = artifact_dir / "tokenizer"
    if not _has_model(model_dir):
        raise ModelArtifactNotFoundError("neutral gate model files were not found")
    if not _has_tokenizer(tokenizer_dir):
        raise ModelArtifactNotFoundError("neutral gate tokenizer files were not found")

    labels_payload = _load_json_object(
        artifact_dir / "label_classes.json",
        "label classes",
    )
    raw_labels = labels_payload.get("classes", labels_payload.get("labels"))
    if raw_labels != list(NEUTRAL_GATE_LABELS):
        raise ModelArtifactNotFoundError("neutral gate label classes are invalid")

    metadata = _load_json_object(artifact_dir / "model_metadata.json", "metadata")
    metadata_threshold = metadata.get("gate_threshold")
    metadata_version = metadata.get("model_version")
    threshold = (
        threshold_override if threshold_override is not None else metadata_threshold
    )
    model_version = (
        model_version_override.strip()
        if model_version_override is not None
        else metadata_version
    )
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
        or not 0.0 <= float(threshold) <= 1.0
    ):
        raise ModelArtifactNotFoundError("neutral gate threshold is invalid")
    if not isinstance(model_version, str) or not model_version.strip():
        raise ModelArtifactNotFoundError("neutral gate model version is invalid")
    return NeutralGateArtifact(
        model_dir=model_dir,
        tokenizer_dir=tokenizer_dir,
        threshold=float(threshold),
        model_version=model_version.strip(),
    )


class NeutralGateAnalyzer:
    """Load one binary classifier and expose calibrated neutral decisions."""

    def __init__(
        self,
        *,
        artifact_dir: Path | None,
        device: str = "auto",
        max_length: int = 128,
        threshold_override: float | None = None,
        model_version_override: str | None = None,
    ) -> None:
        self.artifact_dir = artifact_dir
        self.device = device
        self.max_length = max_length
        self.threshold_override = threshold_override
        self.model_version_override = model_version_override
        self._load_lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self._torch: Any | None = None
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._device: Any | None = None
        self._artifact: NeutralGateArtifact | None = None

    @property
    def is_loaded(self) -> bool:
        return (
            self._model is not None
            and self._tokenizer is not None
            and self._artifact is not None
        )

    @property
    def model_version(self) -> str | None:
        return self._artifact.model_version if self._artifact is not None else None

    @property
    def threshold(self) -> float | None:
        return self._artifact.threshold if self._artifact is not None else None

    def load(self) -> None:
        with self._load_lock:
            if self.is_loaded:
                return
            artifact = resolve_neutral_gate_artifact(
                self.artifact_dir,
                threshold_override=self.threshold_override,
                model_version_override=self.model_version_override,
            )
            try:
                torch = importlib.import_module("torch")
                transformers = importlib.import_module("transformers")
            except ImportError as exc:
                raise OptionalDependencyMissingError(
                    "neutral gate inference requires torch and transformers"
                ) from exc
            selected_device = select_inference_device(torch, self.device)
            device = torch.device(selected_device)
            try:
                tokenizer = transformers.AutoTokenizer.from_pretrained(
                    artifact.tokenizer_dir,
                    local_files_only=True,
                )
                model = transformers.AutoModelForSequenceClassification.from_pretrained(
                    artifact.model_dir,
                    local_files_only=True,
                )
                model.eval()
                model.to(device)
            except Exception as exc:
                raise ModelLoadError(
                    "neutral gate artifacts could not be loaded locally"
                ) from exc
            id2label = {
                int(index): label
                for index, label in dict(model.config.id2label).items()
            }
            label2id = {
                label: int(index)
                for label, index in dict(model.config.label2id).items()
            }
            if (
                model.config.num_labels != 2
                or id2label != {0: "neutral", 1: "emotional"}
                or label2id != {"neutral": 0, "emotional": 1}
            ):
                raise ModelLoadError("neutral gate model labels are invalid")
            separator = getattr(tokenizer, "sep_token", None)
            if not isinstance(separator, str) or not separator.strip():
                raise ModelLoadError("neutral gate tokenizer separator is unavailable")
            self._torch = torch
            self._tokenizer = tokenizer
            self._model = model
            self._device = device
            self._artifact = artifact

    def predict(self, request: CoarseEmotionInput) -> NeutralGateResult:
        if not self.is_loaded:
            raise ModelNotLoadedError("neutral gate model is not loaded")
        assert self._torch is not None
        assert self._tokenizer is not None
        assert self._model is not None
        assert self._artifact is not None
        text = transformer_inference_text(
            request.hs01,
            request.hs02,
            request.hs03,
            self._tokenizer.sep_token,
        )
        started = time.perf_counter()
        try:
            encoded = self._tokenizer(
                text,
                truncation=True,
                max_length=self.max_length,
                padding=True,
                return_tensors="pt",
            )
            moved = {
                name: value.to(self._device) if hasattr(value, "to") else value
                for name, value in encoded.items()
            }
            with self._inference_lock, self._torch.inference_mode():
                values: Sequence[float] = (
                    self._torch.softmax(self._model(**moved).logits, dim=-1)
                    .detach()
                    .cpu()
                    .tolist()[0]
                )
        except RuntimeError as exc:
            raise PredictionExecutionError("neutral gate inference failed") from exc
        except Exception as exc:
            raise PredictionExecutionError("neutral gate inference failed") from exc
        if (
            len(values) != 2
            or any(not math.isfinite(float(value)) for value in values)
            or not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-6)
        ):
            raise PredictionOutputError("neutral gate output is invalid")
        neutral_score, emotional_score = (float(values[0]), float(values[1]))
        decision = (
            NeutralGateDecision.EMOTIONAL
            if emotional_score >= self._artifact.threshold
            else NeutralGateDecision.NEUTRAL
        )
        return NeutralGateResult(
            decision=decision,
            neutral_score=neutral_score,
            emotional_score=emotional_score,
            threshold=self._artifact.threshold,
            model_version=self._artifact.model_version,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


__all__ = [
    "NEUTRAL_GATE_LABELS",
    "NeutralGateAnalyzer",
    "NeutralGateArtifact",
    "NeutralGateResult",
    "resolve_neutral_gate_artifact",
]
