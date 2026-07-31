"""Threshold calibration and guarded metrics for the neutral gate."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..data.neutral_gate_dataset import EMOTIONAL_LABEL, NEUTRAL_LABEL

DEFAULT_GATE_THRESHOLDS = tuple(round(value / 100, 2) for value in range(30, 81, 5))


class NeutralGateEvaluationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScoredGatePrediction:
    true_label: str
    emotional_probability: float

    def __post_init__(self) -> None:
        if self.true_label not in {NEUTRAL_LABEL, EMOTIONAL_LABEL}:
            raise NeutralGateEvaluationError("gate truth label is invalid")
        if (
            isinstance(self.emotional_probability, bool)
            or not isinstance(self.emotional_probability, (int, float))
            or not math.isfinite(float(self.emotional_probability))
            or not 0.0 <= float(self.emotional_probability) <= 1.0
        ):
            raise NeutralGateEvaluationError("gate probability is invalid")


def evaluate_gate_threshold(
    predictions: Sequence[ScoredGatePrediction],
    *,
    threshold: float,
) -> dict[str, object]:
    if not predictions:
        raise NeutralGateEvaluationError("gate predictions are empty")
    if not 0.0 <= threshold <= 1.0:
        raise NeutralGateEvaluationError("gate threshold is invalid")
    tn = fp = fn = tp = 0
    for item in predictions:
        predicted_emotional = item.emotional_probability >= threshold
        if item.true_label == EMOTIONAL_LABEL:
            if predicted_emotional:
                tp += 1
            else:
                fn += 1
        elif predicted_emotional:
            fp += 1
        else:
            tn += 1

    def ratio(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    neutral_recall = ratio(tn, tn + fp)
    neutral_precision = ratio(tn, tn + fn)
    emotional_recall = ratio(tp, tp + fn)
    emotional_precision = ratio(tp, tp + fp)

    def f1(precision: float, recall: float) -> float:
        return (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )

    neutral_fpr = ratio(fp, tn + fp)
    return {
        "threshold": threshold,
        "neutral_false_positive_rate": neutral_fpr,
        "emotional_retention": emotional_recall,
        "neutral": {
            "precision": neutral_precision,
            "recall": neutral_recall,
            "f1": f1(neutral_precision, neutral_recall),
            "support": tn + fp,
        },
        "emotional": {
            "precision": emotional_precision,
            "recall": emotional_recall,
            "f1": f1(emotional_precision, emotional_recall),
            "support": tp + fn,
        },
        "accuracy": ratio(tp + tn, len(predictions)),
        "confusion_matrix": {
            "labels": [NEUTRAL_LABEL, EMOTIONAL_LABEL],
            "matrix": [[tn, fp], [fn, tp]],
        },
        "guarded_score": emotional_recall - neutral_fpr,
        "passes_minimum_guards": neutral_fpr <= 0.10 and emotional_recall >= 0.90,
        "passes_target_guards": neutral_fpr <= 0.05 and emotional_recall >= 0.90,
    }


def threshold_sweep(
    predictions: Sequence[ScoredGatePrediction],
    thresholds: Sequence[float] = DEFAULT_GATE_THRESHOLDS,
) -> list[dict[str, object]]:
    if not thresholds:
        raise NeutralGateEvaluationError("gate threshold grid is empty")
    return [
        evaluate_gate_threshold(predictions, threshold=threshold)
        for threshold in thresholds
    ]


def select_gate_threshold(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    eligible = [row for row in rows if row.get("passes_minimum_guards") is True]
    if not eligible:
        raise NeutralGateEvaluationError(
            "no threshold satisfies neutral FPR and emotional retention guards"
        )

    def metric(row: dict[str, object], name: str) -> float:
        value = row.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise NeutralGateEvaluationError("gate metric is invalid")
        return float(value)

    return max(
        eligible,
        key=lambda row: (
            bool(row.get("passes_target_guards")),
            metric(row, "guarded_score"),
            metric(row, "emotional_retention"),
            -metric(row, "neutral_false_positive_rate"),
            metric(row, "threshold"),
        ),
    )


__all__ = [
    "DEFAULT_GATE_THRESHOLDS",
    "NeutralGateEvaluationError",
    "ScoredGatePrediction",
    "evaluate_gate_threshold",
    "select_gate_threshold",
    "threshold_sweep",
]
