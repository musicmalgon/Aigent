"""Strict Stage 2 partial-multilabel dataset contracts and calibration helpers."""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class BurnoutSignalLabel(StrEnum):
    EXHAUSTION = "exhaustion"
    OVERLOAD = "overload"
    HELPLESSNESS = "helplessness"
    LOW_EFFICACY = "low_efficacy"
    ANXIETY = "anxiety"
    IRRITABILITY = "irritability"


BURNOUT_SIGNAL_LABELS = tuple(BurnoutSignalLabel)
BURNOUT_SIGNAL_VALUES = tuple(label.value for label in BURNOUT_SIGNAL_LABELS)
BURNOUT_SIGNAL_LABEL_TO_ID = {
    label: index for index, label in enumerate(BURNOUT_SIGNAL_LABELS)
}
TRAINING_ROLES = frozenset(
    {"human_gold_train", "weak_unanimous_negative_train"}
)
VALIDATION_ROLE = "independent_human_validation"


class BurnoutMultilabelDataError(ValueError):
    """Raised when local Stage 2 training data violates its contract."""


@dataclass(frozen=True)
class BurnoutMultilabelSample:
    candidate_id: str
    text: str
    labels: tuple[float, ...]
    label_mask: tuple[float, ...]
    sample_weight: float
    dataset_role: str
    group_id: str | None
    normalized_text_cluster_id: str


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BurnoutMultilabelDataError(f"{name} must be a non-empty string")
    return value.strip()


def _parse_row(raw: object, *, validation: bool) -> BurnoutMultilabelSample:
    if not isinstance(raw, Mapping):
        raise BurnoutMultilabelDataError("each JSONL row must be an object")
    expected = {
        "schema_version",
        "candidate_id",
        "dataset_role",
        "text",
        "text_sha256",
        "group_id",
        "normalized_text_cluster_id",
        "labels",
        "label_mask",
        "sample_weight",
    }
    if set(raw) != expected or raw.get("schema_version") != 1:
        raise BurnoutMultilabelDataError("multilabel row fields are invalid")
    role = _required_string(raw.get("dataset_role"), "dataset_role")
    allowed_roles = {VALIDATION_ROLE} if validation else TRAINING_ROLES
    if role not in allowed_roles:
        raise BurnoutMultilabelDataError("dataset_role is invalid for this split")
    candidate_id = _required_string(raw.get("candidate_id"), "candidate_id")
    text = _required_string(raw.get("text"), "text")
    cluster = _required_string(
        raw.get("normalized_text_cluster_id"), "normalized_text_cluster_id"
    )
    group_raw = raw.get("group_id")
    if group_raw is not None and (
        not isinstance(group_raw, str) or not group_raw.strip()
    ):
        raise BurnoutMultilabelDataError("group_id must be null or non-empty")
    labels_raw = raw.get("labels")
    mask_raw = raw.get("label_mask")
    if not isinstance(labels_raw, Mapping) or set(labels_raw) != set(
        BURNOUT_SIGNAL_VALUES
    ):
        raise BurnoutMultilabelDataError("labels must contain exactly six signals")
    if not isinstance(mask_raw, Mapping) or set(mask_raw) != set(
        BURNOUT_SIGNAL_VALUES
    ):
        raise BurnoutMultilabelDataError(
            "label_mask must contain exactly six signals"
        )
    labels: list[float] = []
    masks: list[float] = []
    for label in BURNOUT_SIGNAL_VALUES:
        mask = mask_raw[label]
        value = labels_raw[label]
        if mask not in (0, 1):
            raise BurnoutMultilabelDataError("label_mask values must be 0 or 1")
        if mask == 1 and value not in (0, 1):
            raise BurnoutMultilabelDataError(
                "observed labels must be binary"
            )
        if mask == 0 and value is not None:
            raise BurnoutMultilabelDataError(
                "masked labels must be null"
            )
        labels.append(float(value or 0))
        masks.append(float(mask))
    if sum(masks) == 0:
        raise BurnoutMultilabelDataError(
            "training rows must contain at least one observed label-cell"
        )
    if validation and any(mask != 1.0 for mask in masks):
        raise BurnoutMultilabelDataError(
            "independent validation must have all six labels observed"
        )
    weight = raw.get("sample_weight")
    if (
        isinstance(weight, bool)
        or not isinstance(weight, (int, float))
        or not math.isfinite(float(weight))
        or not 0 < float(weight) <= 1
    ):
        raise BurnoutMultilabelDataError("sample_weight must be in (0, 1]")
    return BurnoutMultilabelSample(
        candidate_id=candidate_id,
        text=text,
        labels=tuple(labels),
        label_mask=tuple(masks),
        sample_weight=float(weight),
        dataset_role=role,
        group_id=group_raw.strip() if isinstance(group_raw, str) else None,
        normalized_text_cluster_id=cluster,
    )


def load_burnout_multilabel_jsonl(
    path: Path, *, validation: bool = False
) -> list[BurnoutMultilabelSample]:
    """Load one strict local JSONL split without leaking raw rows in errors."""

    samples: list[BurnoutMultilabelSample] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    samples.append(_parse_row(json.loads(line), validation=validation))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BurnoutMultilabelDataError("multilabel JSONL is unreadable") from exc
    if not samples:
        raise BurnoutMultilabelDataError("multilabel JSONL is empty")
    ids = [sample.candidate_id for sample in samples]
    if len(ids) != len(set(ids)):
        raise BurnoutMultilabelDataError("candidate IDs must be unique")
    return samples


def validate_split_isolation(
    train: Sequence[BurnoutMultilabelSample],
    validation: Sequence[BurnoutMultilabelSample],
) -> None:
    """Reject candidate, group, or normalized-text leakage."""

    train_ids = {sample.candidate_id for sample in train}
    validation_ids = {sample.candidate_id for sample in validation}
    train_groups = {sample.group_id for sample in train if sample.group_id}
    validation_groups = {
        sample.group_id for sample in validation if sample.group_id
    }
    train_clusters = {sample.normalized_text_cluster_id for sample in train}
    validation_clusters = {
        sample.normalized_text_cluster_id for sample in validation
    }
    if train_ids & validation_ids:
        raise BurnoutMultilabelDataError("candidate leakage detected")
    if train_groups & validation_groups:
        raise BurnoutMultilabelDataError("group leakage detected")
    if train_clusters & validation_clusters:
        raise BurnoutMultilabelDataError("normalized text leakage detected")


def weighted_positive_class_weights(
    samples: Sequence[BurnoutMultilabelSample], *, maximum: float = 20.0
) -> tuple[float, ...]:
    """Return capped neg/pos weights using only observed, weighted cells."""

    if maximum < 1:
        raise BurnoutMultilabelDataError("maximum pos weight must be at least 1")
    weights: list[float] = []
    for index in range(len(BURNOUT_SIGNAL_LABELS)):
        positive = sum(
            sample.sample_weight
            for sample in samples
            if sample.label_mask[index] and sample.labels[index] == 1
        )
        negative = sum(
            sample.sample_weight
            for sample in samples
            if sample.label_mask[index] and sample.labels[index] == 0
        )
        if positive <= 0 or negative <= 0:
            raise BurnoutMultilabelDataError(
                "each label requires observed positive and negative training support"
            )
        weights.append(round(min(maximum, max(1.0, negative / positive)), 6))
    return tuple(weights)


def masked_bce_with_logits(
    logits: Any,
    targets: Any,
    label_mask: Any,
    sample_weight: Any,
    *,
    pos_weight: Any | None = None,
) -> Any:
    """Compute BCE only for observed label-cells, weighted per sample."""

    functional = importlib.import_module("torch.nn.functional")
    if logits.shape != targets.shape or logits.shape != label_mask.shape:
        raise BurnoutMultilabelDataError(
            "logits, targets, and label_mask must share shape"
        )
    if logits.ndim != 2 or logits.shape[1] != len(BURNOUT_SIGNAL_LABELS):
        raise BurnoutMultilabelDataError("multilabel logits must have shape [N, 6]")
    if sample_weight.ndim != 1 or sample_weight.shape[0] != logits.shape[0]:
        raise BurnoutMultilabelDataError("sample_weight must have shape [N]")
    raw = functional.binary_cross_entropy_with_logits(
        logits,
        targets,
        reduction="none",
        pos_weight=pos_weight,
    )
    effective = label_mask * sample_weight.unsqueeze(1)
    denominator = effective.sum()
    if float(denominator.detach().cpu()) <= 0:
        raise BurnoutMultilabelDataError("a batch must contain an observed label-cell")
    return (raw * effective).sum() / denominator


def calibrate_thresholds(
    probabilities: Sequence[Sequence[float]],
    targets: Sequence[Sequence[float]],
    *,
    minimum_precision: float = 0.80,
    minimum_positive_support: int = 5,
    candidates: Sequence[float] = tuple(value / 100 for value in range(20, 96, 5)),
) -> dict[str, Any]:
    """Select conservative per-label thresholds on independent full labels."""

    if len(probabilities) != len(targets) or not probabilities:
        raise BurnoutMultilabelDataError("calibration rows are missing or misaligned")
    rows: dict[str, Any] = {}
    all_validated = True
    for index, label in enumerate(BURNOUT_SIGNAL_VALUES):
        expected = [int(row[index]) for row in targets]
        scores = [float(row[index]) for row in probabilities]
        positive_support = sum(expected)
        eligible: list[dict[str, Any]] = []
        for threshold in candidates:
            tp = sum(y == 1 and score >= threshold for y, score in zip(expected, scores))
            fp = sum(y == 0 and score >= threshold for y, score in zip(expected, scores))
            fn = sum(y == 1 and score < threshold for y, score in zip(expected, scores))
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            if precision >= minimum_precision and tp + fp >= minimum_positive_support:
                eligible.append({
                    "threshold": float(threshold),
                    "precision": precision,
                    "recall": recall,
                    "predicted_positive_support": tp + fp,
                    "true_positive_support": positive_support,
                })
        if eligible and positive_support >= minimum_positive_support:
            selected = max(
                eligible,
                key=lambda item: (
                    item["recall"],
                    item["precision"],
                    item["threshold"],
                ),
            )
            status = "validated"
        else:
            selected = {
                "threshold": 1.0,
                "precision": None,
                "recall": 0.0,
                "predicted_positive_support": 0,
                "true_positive_support": positive_support,
            }
            status = "blocked"
            all_validated = False
        rows[label] = {"status": status, **selected}
    return {
        "status": "validated" if all_validated else "shadow_only",
        "minimum_precision": minimum_precision,
        "minimum_positive_support": minimum_positive_support,
        "labels": rows,
    }


__all__ = [
    "BURNOUT_SIGNAL_LABELS",
    "BURNOUT_SIGNAL_LABEL_TO_ID",
    "BURNOUT_SIGNAL_VALUES",
    "BurnoutMultilabelDataError",
    "BurnoutMultilabelSample",
    "BurnoutSignalLabel",
    "calibrate_thresholds",
    "load_burnout_multilabel_jsonl",
    "masked_bce_with_logits",
    "validate_split_isolation",
    "weighted_positive_class_weights",
]
