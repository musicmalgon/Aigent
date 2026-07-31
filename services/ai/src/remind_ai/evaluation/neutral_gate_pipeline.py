"""Metrics for the neutral gate plus six-class abstention pipeline."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..data.emotion_taxonomy_v2 import EXPECTED_V2_LABELS
from .neutral_gate import (
    EMOTIONAL_LABEL,
    NEUTRAL_LABEL,
    ScoredGatePrediction,
    evaluate_gate_threshold,
)

LETHARGY_LABEL = EXPECTED_V2_LABELS[-1]


class NeutralGatePipelineEvaluationError(ValueError):
    """Raised when cached combined-pipeline scores are invalid."""


@dataclass(frozen=True, slots=True)
class ScoredPipelinePrediction:
    true_gate_label: str
    emotional_probability: float
    true_emotion: str | None
    predicted_emotion: str
    confidence: float
    margin: float
    gate_latency_ms: float | None = None
    coarse_latency_ms: float | None = None

    def __post_init__(self) -> None:
        ScoredGatePrediction(
            true_label=self.true_gate_label,
            emotional_probability=self.emotional_probability,
        )
        if self.true_gate_label == NEUTRAL_LABEL:
            if self.true_emotion is not None:
                raise NeutralGatePipelineEvaluationError(
                    "neutral samples cannot have a true emotion"
                )
        elif self.true_emotion not in EXPECTED_V2_LABELS:
            raise NeutralGatePipelineEvaluationError(
                "emotional samples require a v2 true emotion"
            )
        if self.predicted_emotion not in EXPECTED_V2_LABELS:
            raise NeutralGatePipelineEvaluationError(
                "predicted emotion is outside taxonomy v2"
            )
        if (
            isinstance(self.confidence, bool)
            or not math.isfinite(self.confidence)
            or not 0.0 <= self.confidence <= 1.0
            or isinstance(self.margin, bool)
            or not math.isfinite(self.margin)
            or not 0.0 <= self.margin <= self.confidence
        ):
            raise NeutralGatePipelineEvaluationError(
                "confidence and margin are invalid"
            )
        for latency in (self.gate_latency_ms, self.coarse_latency_ms):
            if latency is not None and (
                isinstance(latency, bool) or not math.isfinite(latency) or latency < 0.0
            ):
                raise NeutralGatePipelineEvaluationError("latency is invalid")


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return (
        round(2.0 * precision * recall / (precision + recall), 6)
        if precision + recall
        else 0.0
    )


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 6)


def evaluate_combined_pipeline(
    predictions: Sequence[ScoredPipelinePrediction],
    *,
    gate_threshold: float,
    confidence_threshold: float = 0.65,
    margin_threshold: float = 0.15,
) -> dict[str, object]:
    """Evaluate gate rejection and downstream accepted emotion quality together."""

    if not predictions:
        raise NeutralGatePipelineEvaluationError("pipeline predictions are empty")
    for value, name in (
        (gate_threshold, "gate threshold"),
        (confidence_threshold, "confidence threshold"),
        (margin_threshold, "margin threshold"),
    ):
        if (
            isinstance(value, bool)
            or not math.isfinite(value)
            or not 0.0 <= value <= 1.0
        ):
            raise NeutralGatePipelineEvaluationError(f"{name} is invalid")

    gate_metrics = evaluate_gate_threshold(
        [
            ScoredGatePrediction(
                true_label=row.true_gate_label,
                emotional_probability=row.emotional_probability,
            )
            for row in predictions
        ],
        threshold=gate_threshold,
    )
    passed = [row for row in predictions if row.emotional_probability >= gate_threshold]
    accepted = [
        row
        for row in passed
        if row.confidence >= confidence_threshold and row.margin >= margin_threshold
    ]
    accepted_emotional = [
        row for row in accepted if row.true_gate_label == EMOTIONAL_LABEL
    ]
    correct_accepted = sum(
        row.true_emotion == row.predicted_emotion for row in accepted_emotional
    )
    per_class: dict[str, dict[str, object]] = {}
    f1_values: list[float] = []
    for label in EXPECTED_V2_LABELS:
        support = sum(row.true_emotion == label for row in predictions)
        predicted_count = sum(row.predicted_emotion == label for row in accepted)
        true_positive = sum(
            row.true_emotion == label and row.predicted_emotion == label
            for row in accepted
        )
        precision = _ratio(true_positive, predicted_count)
        recall = _ratio(true_positive, support)
        class_f1 = _f1(precision, recall)
        f1_values.append(class_f1)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": class_f1,
            "gold_support": support,
            "accepted_predictions": predicted_count,
        }

    neutral_count = sum(row.true_gate_label == NEUTRAL_LABEL for row in predictions)
    neutral_accepted = sum(row.true_gate_label == NEUTRAL_LABEL for row in accepted)
    emotional_count = sum(row.true_gate_label == EMOTIONAL_LABEL for row in predictions)
    gate_latencies = [
        row.gate_latency_ms for row in predictions if row.gate_latency_ms is not None
    ]
    combined_latencies = [
        row.gate_latency_ms + row.coarse_latency_ms
        for row in passed
        if row.gate_latency_ms is not None and row.coarse_latency_ms is not None
    ]
    return {
        "gate_threshold": gate_threshold,
        "confidence_threshold": confidence_threshold,
        "margin_threshold": margin_threshold,
        "gate": gate_metrics,
        "emotional_sample_count": emotional_count,
        "accepted_emotional_count": len(accepted_emotional),
        "accepted_emotional_rate": _ratio(len(accepted_emotional), emotional_count),
        "accepted_precision": _ratio(correct_accepted, len(accepted_emotional)),
        "accepted_macro_f1": round(sum(f1_values) / len(f1_values), 6),
        "per_class": per_class,
        "lethargy_recall": per_class[LETHARGY_LABEL]["recall"],
        "neutral_sample_count": neutral_count,
        "neutral_accepted_count": neutral_accepted,
        "combined_neutral_false_positive_rate": _ratio(neutral_accepted, neutral_count),
        "latency_ms": {
            "gate_p50": _percentile(gate_latencies, 0.50),
            "gate_p95": _percentile(gate_latencies, 0.95),
            "gate_plus_coarse_p50": _percentile(combined_latencies, 0.50),
            "gate_plus_coarse_p95": _percentile(combined_latencies, 0.95),
        },
    }


__all__ = [
    "NeutralGatePipelineEvaluationError",
    "ScoredPipelinePrediction",
    "evaluate_combined_pipeline",
]
