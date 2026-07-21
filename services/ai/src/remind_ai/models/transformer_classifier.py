"""KLUE-RoBERTa classifier construction, device selection, and metrics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import importlib
from typing import Any, Literal

from ..data.transformer_dataset import LabelEncoding


DeviceRequest = Literal["auto", "cpu", "mps", "cuda"]


class TransformerModelError(RuntimeError):
    """A safe model or device configuration failure."""


@dataclass(frozen=True)
class TransformerModelConfig:
    model_name: str = "klue/roberta-base"
    max_length: int = 128


@dataclass(frozen=True)
class DeviceSelection:
    requested: str
    selected: str
    cpu_fallback_used: bool
    fp16_enabled: bool


def _torch() -> Any:
    try:
        return importlib.import_module("torch")
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise TransformerModelError("PyTorch is required for transformer training") from exc


def select_device(
    requested: str = "auto",
    *,
    allow_cpu_fallback: bool = False,
    fp16_requested: bool = False,
    torch_module: Any | None = None,
) -> DeviceSelection:
    """Select CUDA, MPS, or CPU without silently changing explicit requests."""

    if requested not in {"auto", "cpu", "mps", "cuda"}:
        raise TransformerModelError("an unsupported device was requested")
    torch = torch_module or _torch()
    cuda_available = bool(torch.cuda.is_available())
    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    mps_available = bool(mps_backend and mps_backend.is_available())
    if requested == "auto":
        selected = "cuda" if cuda_available else "mps" if mps_available else "cpu"
        if fp16_requested and selected != "cuda":
            raise TransformerModelError("fp16 training requires an available CUDA device")
        return DeviceSelection(requested, selected, False, fp16_requested)
    available = requested == "cpu" or (requested == "cuda" and cuda_available) or (
        requested == "mps" and mps_available
    )
    if available:
        if fp16_requested and requested != "cuda":
            raise TransformerModelError("fp16 training requires an available CUDA device")
        return DeviceSelection(requested, requested, False, fp16_requested)
    if allow_cpu_fallback:
        if fp16_requested:
            raise TransformerModelError("fp16 cannot be used with CPU fallback")
        return DeviceSelection(requested, "cpu", True, False)
    raise TransformerModelError("the requested accelerator is unavailable")


def load_tokenizer(model_name: str) -> Any:
    """Load the user-selected Hugging Face tokenizer on the local machine."""

    try:
        transformers = importlib.import_module("transformers")
        return transformers.AutoTokenizer.from_pretrained(model_name)
    except ImportError as exc:
        raise TransformerModelError(
            "transformers is required for the KLUE-RoBERTa baseline"
        ) from exc
    except Exception as exc:
        raise TransformerModelError("the tokenizer could not be initialized") from exc


def load_classifier(
    config: TransformerModelConfig,
    labels: LabelEncoding,
) -> Any:
    """Create a sequence classifier with an explicit stable class mapping."""

    try:
        transformers = importlib.import_module("transformers")
        return transformers.AutoModelForSequenceClassification.from_pretrained(
            config.model_name,
            num_labels=len(labels.classes),
            label2id=dict(labels.label2id),
            id2label=dict(labels.id2label),
        )
    except ImportError as exc:
        raise TransformerModelError(
            "transformers is required for the KLUE-RoBERTa baseline"
        ) from exc
    except Exception as exc:
        raise TransformerModelError("the classifier could not be initialized") from exc


def create_data_collator(tokenizer: Any) -> Any:
    """Create dynamic padding; fixed padding is intentionally not used."""

    try:
        transformers = importlib.import_module("transformers")
        return transformers.DataCollatorWithPadding(tokenizer=tokenizer)
    except ImportError as exc:
        raise TransformerModelError(
            "transformers is required for dynamic padding"
        ) from exc


def classification_metrics(
    expected_ids: Sequence[int],
    predicted_ids: Sequence[int],
    labels: LabelEncoding,
) -> dict[str, object]:
    """Compute aggregate multiclass metrics without record-level output."""

    if not expected_ids or len(expected_ids) != len(predicted_ids):
        raise TransformerModelError("evaluation predictions have an invalid size")
    try:
        metrics = importlib.import_module("sklearn.metrics")
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise TransformerModelError("scikit-learn is required for evaluation") from exc
    label_ids = list(range(len(labels.classes)))
    precision, recall, f1, support = metrics.precision_recall_fscore_support(
        expected_ids,
        predicted_ids,
        labels=label_ids,
        zero_division=0,
    )
    macro_precision, macro_recall, macro_f1, _ = (
        metrics.precision_recall_fscore_support(
            expected_ids, predicted_ids, average="macro", zero_division=0
        )
    )
    weighted_f1 = metrics.precision_recall_fscore_support(
        expected_ids, predicted_ids, average="weighted", zero_division=0
    )[2]
    predicted_names = [labels.id2label[index] for index in predicted_ids]
    expected_names = [labels.id2label[index] for index in expected_ids]
    return {
        "sample_count": len(expected_ids),
        "accuracy": round(float(metrics.accuracy_score(expected_ids, predicted_ids)), 6),
        "macro_precision": round(float(macro_precision), 6),
        "macro_recall": round(float(macro_recall), 6),
        "macro_f1": round(float(macro_f1), 6),
        "weighted_f1": round(float(weighted_f1), 6),
        "per_class": {
            label: {
                "label_id": index,
                "label_name": label,
                "precision": round(float(precision[index]), 6),
                "recall": round(float(recall[index]), 6),
                "f1": round(float(f1[index]), 6),
                "support": int(support[index]),
            }
            for index, label in enumerate(labels.classes)
        },
        "confusion_matrix": {
            "labels": list(labels.classes),
            "matrix": metrics.confusion_matrix(
                expected_ids, predicted_ids, labels=label_ids
            ).tolist(),
        },
        "true_class_distribution": dict(sorted(Counter(expected_names).items())),
        "predicted_class_distribution": dict(sorted(Counter(predicted_names).items())),
    }


def comparison_payload(
    transformer_metrics: Mapping[str, object] | None,
    tfidf_metrics: Mapping[str, object],
    *,
    model_name: str,
    selected_tfidf_model: str,
) -> dict[str, object]:
    """Build a safe comparison using the internal test macro-F1 only."""

    def numeric_metric(source: Mapping[str, object], name: str) -> float:
        value = source.get(name)
        if not isinstance(value, (int, float)):
            raise TransformerModelError("a comparison metric is invalid")
        return float(value)

    tfidf_macro = numeric_metric(tfidf_metrics, "macro_f1")
    transformer_macro = (
        numeric_metric(transformer_metrics, "macro_f1")
        if transformer_metrics is not None
        else None
    )
    absolute = None if transformer_macro is None else transformer_macro - tfidf_macro
    relative = None if absolute is None or tfidf_macro == 0 else absolute / tfidf_macro
    return {
        "evaluation_policy": {
            "primary_metric": "internal_test_macro_f1",
            "official_validation_is_reference_only": True,
        },
        "tfidf": {
            "selected_model": selected_tfidf_model,
            "internal_test_accuracy": tfidf_metrics.get("accuracy"),
            "internal_test_macro_f1": tfidf_metrics.get("macro_f1"),
            "internal_test_weighted_f1": tfidf_metrics.get("weighted_f1"),
        },
        "transformer": {
            "model_name": model_name,
            "internal_test_accuracy": (
                transformer_metrics.get("accuracy") if transformer_metrics else None
            ),
            "internal_test_macro_f1": transformer_macro,
            "internal_test_weighted_f1": (
                transformer_metrics.get("weighted_f1") if transformer_metrics else None
            ),
        },
        "absolute_macro_f1_improvement": (
            round(absolute, 6) if absolute is not None else None
        ),
        "relative_macro_f1_improvement": (
            round(relative, 6) if relative is not None else None
        ),
    }
