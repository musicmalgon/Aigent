"""Production-facing adapter for the validated six-class Transformer model."""

from __future__ import annotations

import importlib
import json
import logging
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..remind_ai.data.transformer_dataset import transformer_inference_text
from ..schemas import (
    REMIND_COARSE_EMOTION_LABEL_TO_ID,
    REMIND_COARSE_EMOTION_LABELS,
    REMIND_COARSE_EMOTION_SCHEMA_VERSION,
    CoarseEmotionInput,
    RemindCoarseEmotionInferenceResponse,
    RemindCoarseEmotionTopPrediction,
    UncertaintyReason,
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
from .coarse_settings import TRAINING_MAX_LENGTH, CoarseEmotionSettings

LOGGER = logging.getLogger(__name__)
EXPECTED_ID2LABEL = {
    index: label.value for index, label in enumerate(REMIND_COARSE_EMOTION_LABELS)
}
EXPECTED_LABEL2ID = {label: index for index, label in EXPECTED_ID2LABEL.items()}
MODEL_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
TOKENIZER_FILES = ("tokenizer.json", "vocab.txt")


@dataclass(frozen=True)
class CoarseArtifactPaths:
    model_dir: Path
    tokenizer_dir: Path
    label_classes_path: Path | None
    label_mapping_path: Path | None
    run_config_path: Path | None


def _has_model(directory: Path) -> bool:
    return (directory / "config.json").is_file() and any(
        (directory / filename).is_file() for filename in MODEL_WEIGHT_FILES
    )


def _has_tokenizer(directory: Path) -> bool:
    return any((directory / filename).is_file() for filename in TOKENIZER_FILES)


def _first_matching(candidates: Sequence[Path], predicate: Any) -> Path | None:
    return next((candidate for candidate in candidates if predicate(candidate)), None)


def resolve_coarse_artifacts(
    *,
    artifact_dir: str | Path | None = None,
    model_dir: str | Path | None = None,
    tokenizer_dir: str | Path | None = None,
    label_mapping_path: str | Path | None = None,
) -> CoarseArtifactPaths:
    """Resolve split or single-directory Hugging Face artifact layouts."""

    root = Path(artifact_dir) if artifact_dir is not None else None
    if root is not None and not root.is_dir():
        raise ModelArtifactNotFoundError("coarse artifact directory was not found")
    explicit_model = Path(model_dir) if model_dir is not None else None
    explicit_tokenizer = Path(tokenizer_dir) if tokenizer_dir is not None else None
    if root is None and explicit_model is None:
        raise ModelArtifactNotConfiguredError(
            "configure EMOTION_ARTIFACT_DIR or EMOTION_MODEL_DIR"
        )

    model_candidates = (
        [root / "model", root / "checkpoints" / "best", root]
        if root is not None
        else []
    )
    resolved_model = explicit_model or _first_matching(model_candidates, _has_model)
    if resolved_model is None or not _has_model(resolved_model):
        raise ModelArtifactNotFoundError(
            "coarse model config and weight files were not found"
        )

    tokenizer_candidates: list[Path] = []
    if root is not None:
        tokenizer_candidates.extend(
            [root / "tokenizer", root / "checkpoints" / "best", root]
        )
    tokenizer_candidates.append(resolved_model)
    resolved_tokenizer = explicit_tokenizer or _first_matching(
        tokenizer_candidates, _has_tokenizer
    )
    if resolved_tokenizer is None or not _has_tokenizer(resolved_tokenizer):
        raise ModelArtifactNotFoundError("coarse tokenizer files were not found")

    label_classes = (
        root / "label_classes.json"
        if root is not None and (root / "label_classes.json").is_file()
        else None
    )
    mapping = Path(label_mapping_path) if label_mapping_path is not None else None
    if mapping is not None and not mapping.is_file():
        raise ModelArtifactNotFoundError("coarse label mapping file was not found")
    run_config = (
        root / "run_config.json"
        if root is not None and (root / "run_config.json").is_file()
        else None
    )
    return CoarseArtifactPaths(
        model_dir=resolved_model,
        tokenizer_dir=resolved_tokenizer,
        label_classes_path=label_classes,
        label_mapping_path=mapping,
        run_config_path=run_config,
    )


def _read_json_object(path: Path, description: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelLoadError(f"{description} is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ModelLoadError(f"{description} must contain a JSON object")
    return payload


def _validated_config_labels(config: Mapping[str, object]) -> None:
    raw_id2label = config.get("id2label")
    raw_label2id = config.get("label2id")
    if not isinstance(raw_id2label, Mapping) or not isinstance(raw_label2id, Mapping):
        raise ModelLoadError("model config must contain id2label and label2id")
    try:
        id2label = {int(index): str(label) for index, label in raw_id2label.items()}
        label2id = {str(label): int(index) for label, index in raw_label2id.items()}
    except (TypeError, ValueError) as exc:
        raise ModelLoadError("model label metadata is invalid") from exc
    raw_num_labels = config.get("num_labels", len(id2label))
    if not isinstance(raw_num_labels, int) or raw_num_labels != 6:
        raise ModelLoadError("coarse model must have num_labels=6")
    if id2label != EXPECTED_ID2LABEL or label2id != EXPECTED_LABEL2ID:
        raise ModelLoadError("model label order does not match the coarse contract")


def validate_coarse_artifact_metadata(paths: CoarseArtifactPaths) -> None:
    """Reject fine-grained or mislabeled artifacts before loading large weights."""

    config = _read_json_object(paths.model_dir / "config.json", "model config")
    _validated_config_labels(config)
    if paths.label_classes_path is not None:
        labels = _read_json_object(paths.label_classes_path, "label classes")
        if (
            labels.get("classes") != list(EXPECTED_LABEL2ID)
            or labels.get("id2label")
            != {str(index): label for index, label in EXPECTED_ID2LABEL.items()}
            or labels.get("label2id") != EXPECTED_LABEL2ID
            or labels.get("label_set_version")
            != REMIND_COARSE_EMOTION_SCHEMA_VERSION
        ):
            raise ModelLoadError("label classes do not match the v2 contract")
    if paths.label_mapping_path is not None:
        mapping = _read_json_object(paths.label_mapping_path, "label mapping")
        if mapping.get("coarse_labels") != [
            label.value for label in REMIND_COARSE_EMOTION_LABELS
        ]:
            raise ModelLoadError("label mapping does not match the coarse contract")
    if paths.run_config_path is not None:
        run_config = _read_json_object(paths.run_config_path, "run config")
        if (
            run_config.get("label_level") != "coarse-v2"
            or run_config.get("label_set_version")
            != REMIND_COARSE_EMOTION_SCHEMA_VERSION
            or run_config.get("num_labels") != 6
        ):
            raise ModelLoadError("run config is not a six-class v2 experiment")
        artifact_max_length = run_config.get("max_length")
        if (
            artifact_max_length is not None
            and artifact_max_length != TRAINING_MAX_LENGTH
        ):
            raise ModelLoadError(
                "run config max_length does not match the inference contract"
            )


def select_inference_device(torch: Any, requested: str) -> str:
    """Select a device without silently changing an explicit request."""

    normalized = requested.casefold()
    if normalized not in {"auto", "cpu", "cuda", "mps"}:
        raise ModelLoadError("device must be auto, cpu, cuda, or mps")
    cuda_available = bool(torch.cuda.is_available())
    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    mps_available = bool(mps_backend and mps_backend.is_available())
    if normalized == "auto":
        return "cuda" if cuda_available else "mps" if mps_available else "cpu"
    if normalized == "cuda" and not cuda_available:
        raise ModelLoadError("CUDA was requested but is unavailable")
    if normalized == "mps" and not mps_available:
        raise ModelLoadError("MPS was requested but is unavailable")
    return normalized


def classify_uncertainty(
    probabilities: Sequence[float],
    *,
    confidence_threshold: float,
    margin_threshold: float,
) -> UncertaintyReason | None:
    ordered = sorted((float(value) for value in probabilities), reverse=True)
    if len(ordered) != 6:
        raise PredictionOutputError("coarse inference must return six probabilities")
    low_confidence = ordered[0] < confidence_threshold
    small_margin = ordered[0] - ordered[1] < margin_threshold
    if low_confidence and small_margin:
        return UncertaintyReason.LOW_CONFIDENCE_AND_SMALL_MARGIN
    if low_confidence:
        return UncertaintyReason.LOW_CONFIDENCE
    if small_margin:
        return UncertaintyReason.SMALL_MARGIN
    return None


class CoarseTransformerEmotionAnalyzer:
    """Load one validated model and return all six class probabilities."""

    def __init__(self, settings: CoarseEmotionSettings) -> None:
        self.settings = settings
        self._load_lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self._torch: Any | None = None
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._device: Any | None = None
        self._device_name: str | None = None
        self._load_count = 0

    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    @property
    def load_count(self) -> int:
        return self._load_count

    @property
    def device_name(self) -> str | None:
        return self._device_name

    @staticmethod
    def _import_dependencies() -> tuple[Any, Any]:
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
        except ImportError as exc:
            raise OptionalDependencyMissingError(
                "coarse Transformer inference requires torch and transformers"
            ) from exc
        return torch, transformers

    def _paths(self) -> CoarseArtifactPaths:
        return resolve_coarse_artifacts(
            artifact_dir=self.settings.artifact_dir,
            model_dir=self.settings.model_dir,
            tokenizer_dir=self.settings.tokenizer_dir,
            label_mapping_path=self.settings.label_mapping_path,
        )

    def load(self) -> None:
        with self._load_lock:
            if self.is_loaded:
                return
            paths = self._paths()
            validate_coarse_artifact_metadata(paths)
            torch, transformers = self._import_dependencies()
            device_name = select_inference_device(torch, self.settings.device)
            device = torch.device(device_name)
            try:
                tokenizer = transformers.AutoTokenizer.from_pretrained(
                    paths.tokenizer_dir,
                    local_files_only=True,
                )
                model = transformers.AutoModelForSequenceClassification.from_pretrained(
                    paths.model_dir,
                    local_files_only=True,
                )
                model.eval()
                model.to(device)
            except Exception as exc:
                raise ModelLoadError(
                    "coarse Transformer artifacts could not be loaded locally"
                ) from exc
            loaded_config = {
                "num_labels": getattr(model.config, "num_labels", None),
                "id2label": getattr(model.config, "id2label", None),
                "label2id": getattr(model.config, "label2id", None),
            }
            _validated_config_labels(loaded_config)
            separator = getattr(tokenizer, "sep_token", None)
            if not isinstance(separator, str) or not separator.strip():
                raise ModelLoadError("tokenizer separator token is unavailable")
            self._torch = torch
            self._tokenizer = tokenizer
            self._model = model
            self._device = device
            self._device_name = device_name
            self._load_count += 1
            LOGGER.info(
                "coarse emotion model loaded on %s for version %s",
                device_name,
                self.settings.model_version,
            )

    def predict(
        self, request: CoarseEmotionInput
    ) -> RemindCoarseEmotionInferenceResponse:
        return self.predict_batch([request])[0]

    def predict_batch(
        self, requests: Sequence[CoarseEmotionInput]
    ) -> list[RemindCoarseEmotionInferenceResponse]:
        if not requests:
            raise ValueError("at least one inference request is required")
        if not self.is_loaded:
            raise ModelNotLoadedError("coarse emotion model is not loaded")
        assert self._torch is not None
        assert self._tokenizer is not None
        assert self._model is not None
        texts = [
            transformer_inference_text(
                request.hs01,
                request.hs02,
                request.hs03,
                self._tokenizer.sep_token,
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
            if not isinstance(encoded, Mapping):
                raise TypeError("tokenizer output is not a mapping")
            moved = {
                name: value.to(self._device) if hasattr(value, "to") else value
                for name, value in encoded.items()
            }
            with self._inference_lock, self._torch.inference_mode():
                logits = self._model(**moved).logits
                probability_rows = self._torch.softmax(logits, dim=-1).detach().cpu().tolist()
        except RuntimeError as exc:
            if "out of memory" in str(exc).casefold():
                raise PredictionExecutionError(
                    "coarse emotion inference exhausted accelerator memory"
                ) from exc
            raise PredictionExecutionError("coarse emotion inference failed") from exc
        except Exception as exc:
            raise PredictionExecutionError("coarse emotion inference failed") from exc

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            if len(probability_rows) != len(requests):
                raise PredictionOutputError("model output batch size is invalid")
            per_item_latency = elapsed_ms / len(requests)
            responses = [
                self._response_from_probabilities(row, per_item_latency)
                for row in probability_rows
            ]
        except PredictionOutputError:
            raise
        except Exception as exc:
            raise PredictionOutputError(
                "coarse model output violates the response contract"
            ) from exc
        LOGGER.info(
            "coarse emotion inference completed: count=%d latency_ms=%.3f",
            len(requests),
            elapsed_ms,
        )
        return responses

    def _response_from_probabilities(
        self, values: Sequence[float], latency_ms: float
    ) -> RemindCoarseEmotionInferenceResponse:
        if len(values) != 6:
            raise PredictionOutputError("model output does not contain six logits")
        probabilities = {
            label: float(values[index])
            for index, label in enumerate(REMIND_COARSE_EMOTION_LABELS)
        }
        ordered = sorted(
            probabilities.items(),
            key=lambda item: (
                -item[1],
                REMIND_COARSE_EMOTION_LABEL_TO_ID[item[0]],
            ),
        )
        winner, confidence = ordered[0]
        margin = confidence - ordered[1][1]
        reason = classify_uncertainty(
            values,
            confidence_threshold=self.settings.confidence_threshold,
            margin_threshold=self.settings.margin_threshold,
        )
        return RemindCoarseEmotionInferenceResponse(
            label_schema_version="remind-coarse-v2",
            model_version=self.settings.model_version,
            threshold_version=self.settings.threshold_version,
            predicted_emotion=winner,
            predicted_label_id=REMIND_COARSE_EMOTION_LABEL_TO_ID[winner],
            emotion=None if reason is not None else winner,
            confidence=confidence,
            margin=margin,
            provisional=reason is not None,
            is_uncertain=reason is not None,
            uncertainty_reason=reason,
            probabilities=probabilities,
            top_predictions=[
                RemindCoarseEmotionTopPrediction(
                    emotion=label,
                    label_id=REMIND_COARSE_EMOTION_LABEL_TO_ID[label],
                    probability=probability,
                )
                for label, probability in ordered[: self.settings.top_k]
            ],
            latency_ms=float(latency_ms),
        )


__all__ = [
    "CoarseArtifactPaths",
    "CoarseTransformerEmotionAnalyzer",
    "classify_uncertainty",
    "resolve_coarse_artifacts",
    "select_inference_device",
    "validate_coarse_artifact_metadata",
]
