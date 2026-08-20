"""Local inference adapter for the Stage 2 six-signal multilabel model."""

from __future__ import annotations

import importlib
import json
import os
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..schemas import (
    BURNOUT_SIGNAL_LABELS,
    BurnoutSignalInferenceResponse,
    BurnoutSignalLabel,
    BurnoutSignalState,
    CoarseEmotionInput,
)
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

MODEL_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
TOKENIZER_FILES = ("tokenizer.json", "vocab.txt")
EXPECTED_LABELS = tuple(label.value for label in BURNOUT_SIGNAL_LABELS)


def _environment_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("BURNOUT_SIGNALS_ENABLED must be a boolean")


@dataclass(frozen=True)
class BurnoutSignalSettings:
    enabled: bool = False
    artifact_dir: Path | None = None
    device: str = "auto"
    max_length: int = 256

    def __post_init__(self) -> None:
        if self.enabled and self.artifact_dir is None:
            raise ValueError(
                "BURNOUT_SIGNALS_ARTIFACT_DIR is required when enabled"
            )
        if self.device not in {"auto", "cpu", "cuda", "mps"}:
            raise ValueError("burnout signal device must be auto, cpu, cuda, or mps")
        if not 32 <= self.max_length <= 512:
            raise ValueError("burnout signal max length must be between 32 and 512")

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> BurnoutSignalSettings:
        values = os.environ if environment is None else environment
        raw_path = values.get("BURNOUT_SIGNALS_ARTIFACT_DIR", "").strip()
        raw_max_length = values.get("BURNOUT_SIGNALS_MAX_LENGTH", "256").strip()
        try:
            max_length = int(raw_max_length)
        except ValueError as exc:
            raise ValueError("BURNOUT_SIGNALS_MAX_LENGTH must be an integer") from exc
        return cls(
            enabled=_environment_bool(
                values.get("BURNOUT_SIGNALS_ENABLED"), default=False
            ),
            artifact_dir=Path(raw_path) if raw_path else None,
            device=values.get("BURNOUT_SIGNALS_DEVICE", "auto").strip().casefold(),
            max_length=max_length,
        )


def _read_json(path: Path, description: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelLoadError(f"{description} is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ModelLoadError(f"{description} must contain a JSON object")
    return payload


def _validate_label_mapping(payload: Mapping[str, Any]) -> None:
    if payload.get("labels") != list(EXPECTED_LABELS):
        raise ModelLoadError("burnout signal label order is invalid")
    expected_label2id = {label: index for index, label in enumerate(EXPECTED_LABELS)}
    expected_id2label = {str(index): label for index, label in enumerate(EXPECTED_LABELS)}
    if payload.get("label2id") != expected_label2id:
        raise ModelLoadError("burnout signal label2id is invalid")
    if payload.get("id2label") != expected_id2label:
        raise ModelLoadError("burnout signal id2label is invalid")


class BurnoutSignalTransformerAnalyzer:
    """Return calibrated independent probabilities without changing risk scores."""

    def __init__(self, settings: BurnoutSignalSettings) -> None:
        self.settings = settings
        self._load_lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self._torch: Any | None = None
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._device: Any | None = None
        self._thresholds: dict[BurnoutSignalLabel, float] = {}
        self._validated: frozenset[BurnoutSignalLabel] = frozenset()
        self._model_version = ""
        self._threshold_version = ""

    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    @property
    def readiness_metadata(self) -> dict[str, object]:
        return {
            "enabled": self.settings.enabled,
            "loaded": self.is_loaded,
            "deployment_status": self._deployment_status(),
        }

    def _deployment_status(self) -> str:
        count = len(self._validated)
        if count == len(BURNOUT_SIGNAL_LABELS):
            return "validated"
        return "partial" if count else "shadow_only"

    def load(self) -> None:
        with self._load_lock:
            if self.is_loaded:
                return
            root = self.settings.artifact_dir
            if root is None:
                raise ModelArtifactNotConfiguredError(
                    "configure BURNOUT_SIGNALS_ARTIFACT_DIR"
                )
            model_dir = root / "model"
            tokenizer_dir = root / "tokenizer"
            required = (
                root / "thresholds.json",
                root / "label_mapping.json",
                root / "run_config.json",
                model_dir / "config.json",
            )
            if not root.is_dir() or not all(path.is_file() for path in required):
                raise ModelArtifactNotFoundError(
                    "burnout signal artifact is incomplete"
                )
            if not any((model_dir / name).is_file() for name in MODEL_WEIGHT_FILES):
                raise ModelArtifactNotFoundError("burnout signal model weights are missing")
            if not any((tokenizer_dir / name).is_file() for name in TOKENIZER_FILES):
                raise ModelArtifactNotFoundError("burnout signal tokenizer is missing")

            mapping = _read_json(root / "label_mapping.json", "label mapping")
            _validate_label_mapping(mapping)
            run_config = _read_json(root / "run_config.json", "run config")
            if (
                run_config.get("artifact_role") != "stage2_burnout_multilabel_model"
                or run_config.get("task_type") != "multi_label_classification"
                or run_config.get("labels") != list(EXPECTED_LABELS)
                or run_config.get("max_length") != self.settings.max_length
            ):
                raise ModelLoadError("run config does not match the Stage 2 contract")
            thresholds_payload = _read_json(root / "thresholds.json", "thresholds")
            raw_rows = thresholds_payload.get("labels")
            if not isinstance(raw_rows, Mapping) or set(raw_rows) != set(EXPECTED_LABELS):
                raise ModelLoadError("thresholds must contain exactly six signals")
            thresholds: dict[BurnoutSignalLabel, float] = {}
            validated: set[BurnoutSignalLabel] = set()
            for label in BURNOUT_SIGNAL_LABELS:
                row = raw_rows.get(label.value)
                if not isinstance(row, Mapping) or row.get("status") not in {
                    "validated",
                    "blocked",
                }:
                    raise ModelLoadError("threshold status is invalid")
                threshold = row.get("threshold")
                if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                    raise ModelLoadError("threshold must be numeric")
                threshold_value = float(threshold)
                if not 0.0 <= threshold_value <= 1.0:
                    raise ModelLoadError("threshold must be between zero and one")
                thresholds[label] = threshold_value
                if row.get("status") == "validated":
                    validated.add(label)

            model_version = run_config.get("model_version")
            threshold_version = thresholds_payload.get("threshold_version")
            if not isinstance(model_version, str) or not model_version.strip():
                raise ModelLoadError("model version is missing")
            if not isinstance(threshold_version, str) or not threshold_version.strip():
                raise ModelLoadError("threshold version is missing")
            try:
                torch = importlib.import_module("torch")
                transformers = importlib.import_module("transformers")
            except ImportError as exc:
                raise OptionalDependencyMissingError(
                    "burnout signal inference requires torch and transformers"
                ) from exc
            device_name = select_inference_device(torch, self.settings.device)
            try:
                tokenizer = transformers.AutoTokenizer.from_pretrained(
                    tokenizer_dir, local_files_only=True
                )
                model = transformers.AutoModelForSequenceClassification.from_pretrained(
                    model_dir, local_files_only=True
                )
                if getattr(model.config, "problem_type", None) != "multi_label_classification":
                    raise ValueError("model is not configured for multilabel inference")
                loaded_labels = tuple(
                    str(getattr(model.config, "id2label", {}).get(index, ""))
                    for index in range(6)
                )
                if loaded_labels != EXPECTED_LABELS:
                    raise ValueError("loaded label order is invalid")
                model.eval()
                device = torch.device(device_name)
                model.to(device)
            except Exception as exc:
                raise ModelLoadError(
                    "burnout signal artifacts could not be loaded locally"
                ) from exc
            self._torch = torch
            self._tokenizer = tokenizer
            self._model = model
            self._device = device
            self._thresholds = thresholds
            self._validated = frozenset(validated)
            self._model_version = model_version.strip()
            self._threshold_version = threshold_version.strip()

    def predict(self, request: CoarseEmotionInput) -> BurnoutSignalInferenceResponse:
        return self.predict_batch([request])[0]

    def predict_batch(
        self, requests: Sequence[CoarseEmotionInput]
    ) -> list[BurnoutSignalInferenceResponse]:
        if not requests:
            raise ValueError("at least one inference request is required")
        if not self.is_loaded:
            raise ModelNotLoadedError("burnout signal model is not loaded")
        assert self._torch is not None
        assert self._tokenizer is not None
        assert self._model is not None
        separator = self._tokenizer.sep_token
        texts = [
            f" {separator} ".join(
                part for part in (request.hs01, request.hs02, request.hs03) if part
            )
            for request in requests
        ]
        started = time.perf_counter()
        try:
            encoded = self._tokenizer(
                texts,
                truncation=True,
                max_length=self.settings.max_length,
                padding=True,
                return_tensors="pt",
            )
            moved = {
                name: value.to(self._device) if hasattr(value, "to") else value
                for name, value in encoded.items()
            }
            with self._inference_lock, self._torch.inference_mode():
                logits = self._model(**moved).logits
                rows = self._torch.sigmoid(logits).detach().cpu().tolist()
        except RuntimeError as exc:
            if "out of memory" in str(exc).casefold():
                raise PredictionExecutionError(
                    "burnout signal inference exhausted accelerator memory"
                ) from exc
            raise PredictionExecutionError("burnout signal inference failed") from exc
        except Exception as exc:
            raise PredictionExecutionError("burnout signal inference failed") from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if len(rows) != len(requests):
            raise PredictionOutputError("burnout signal batch size is invalid")
        return [
            self._response(row, elapsed_ms / len(requests)) for row in rows
        ]

    def _response(
        self, values: Sequence[float], latency_ms: float
    ) -> BurnoutSignalInferenceResponse:
        if len(values) != len(BURNOUT_SIGNAL_LABELS):
            raise PredictionOutputError("burnout signal output must have six values")
        probabilities = {
            label: float(values[index])
            for index, label in enumerate(BURNOUT_SIGNAL_LABELS)
        }
        states = {
            label: (
                BurnoutSignalState.UNVALIDATED
                if label not in self._validated
                else BurnoutSignalState.PRESENT
                if probabilities[label] >= self._thresholds[label]
                else BurnoutSignalState.ABSENT
            )
            for label in BURNOUT_SIGNAL_LABELS
        }
        active = [
            label
            for label in BURNOUT_SIGNAL_LABELS
            if states[label] is BurnoutSignalState.PRESENT
        ]
        return BurnoutSignalInferenceResponse(
            taxonomy_version="stage2-burnout-signals-v1",
            model_version=self._model_version,
            threshold_version=self._threshold_version,
            probabilities=probabilities,
            thresholds=self._thresholds,
            signal_states=states,
            active_signals=active,
            validated_signals=[
                label for label in BURNOUT_SIGNAL_LABELS if label in self._validated
            ],
            deployment_status=self._deployment_status(),
            informational_only=True,
            risk_score_eligible=False,
            latency_ms=float(latency_ms),
        )


__all__ = [
    "BurnoutSignalSettings",
    "BurnoutSignalTransformerAnalyzer",
]
