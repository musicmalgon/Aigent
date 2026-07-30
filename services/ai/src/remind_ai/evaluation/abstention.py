"""Selective-classification metrics for confidence-and-margin abstention."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..data.emotion_taxonomy_v2 import EXPECTED_V2_LABELS

NEUTRAL_LABEL = "중립"
ABSTAIN_LABEL = "abstain"
HELPLESSNESS_LABEL = EXPECTED_V2_LABELS[-1]
DEFAULT_CONFIDENCE_THRESHOLDS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
DEFAULT_MARGIN_THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.25)
DEFAULT_CONFIDENCE_BINS = (0.0, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0)
DEFAULT_MARGIN_BINS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 1.0)


class AbstentionEvaluationError(ValueError):
    """Raised when score records or evaluation settings are invalid."""


@dataclass(frozen=True)
class ScoredEmotionPrediction:
    """One gold label and one model top-1 prediction without source text."""

    true_label: str
    predicted_label: str
    confidence: float
    margin: float

    def __post_init__(self) -> None:
        allowed_true_labels = {*EXPECTED_V2_LABELS, NEUTRAL_LABEL}
        if self.true_label not in allowed_true_labels:
            raise AbstentionEvaluationError("true_label is outside the evaluation labels")
        if self.predicted_label not in EXPECTED_V2_LABELS:
            raise AbstentionEvaluationError(
                "predicted_label is outside the emotion taxonomy"
            )
        if (
            not math.isfinite(self.confidence)
            or not 0.0 <= self.confidence <= 1.0
            or not math.isfinite(self.margin)
            or not 0.0 <= self.margin <= 1.0
            or self.margin > self.confidence
        ):
            raise AbstentionEvaluationError(
                "confidence and margin must be finite valid probabilities"
            )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    denominator = precision + recall
    return round(2.0 * precision * recall / denominator, 6) if denominator else 0.0


def _validated_threshold(value: float, name: str) -> float:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise AbstentionEvaluationError(f"{name} must be between zero and one")
    return float(value)


def _is_accepted(
    prediction: ScoredEmotionPrediction,
    confidence_threshold: float,
    margin_threshold: float,
) -> bool:
    return (
        prediction.confidence >= confidence_threshold
        and prediction.margin >= margin_threshold
    )


def evaluate_threshold(
    predictions: Sequence[ScoredEmotionPrediction],
    *,
    confidence_threshold: float,
    margin_threshold: float,
) -> dict[str, object]:
    """Evaluate selective prediction quality at one threshold pair.

    Per-class recall uses every gold sample in the denominator, including
    abstained samples. This makes the metric reflect both classification and
    coverage rather than hiding rejected examples.
    """

    confidence_threshold = _validated_threshold(
        confidence_threshold, "confidence_threshold"
    )
    margin_threshold = _validated_threshold(margin_threshold, "margin_threshold")
    if not predictions:
        raise AbstentionEvaluationError("at least one scored prediction is required")

    accepted = [
        prediction
        for prediction in predictions
        if _is_accepted(prediction, confidence_threshold, margin_threshold)
    ]
    accepted_count = len(accepted)
    correct_accepted = sum(
        prediction.true_label == prediction.predicted_label for prediction in accepted
    )
    per_class: dict[str, dict[str, object]] = {}
    for label in EXPECTED_V2_LABELS:
        predicted_as_label = sum(
            prediction.predicted_label == label for prediction in accepted
        )
        true_label_count = sum(
            prediction.true_label == label for prediction in predictions
        )
        true_positive = sum(
            prediction.true_label == label
            and prediction.predicted_label == label
            for prediction in accepted
        )
        precision = _ratio(true_positive, predicted_as_label)
        recall = _ratio(true_positive, true_label_count)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
            "gold_support": true_label_count,
            "accepted_predictions": predicted_as_label,
            "correct_accepted": true_positive,
        }

    row_labels = list(EXPECTED_V2_LABELS)
    neutral_count = sum(
        prediction.true_label == NEUTRAL_LABEL for prediction in predictions
    )
    if neutral_count:
        row_labels.append(NEUTRAL_LABEL)
    column_labels = [*EXPECTED_V2_LABELS, ABSTAIN_LABEL]
    confusion_matrix = [
        [
            sum(
                prediction.true_label == true_label
                and (
                    prediction.predicted_label == predicted_label
                    if predicted_label != ABSTAIN_LABEL
                    else not _is_accepted(
                        prediction, confidence_threshold, margin_threshold
                    )
                )
                and (
                    predicted_label == ABSTAIN_LABEL
                    or _is_accepted(
                        prediction, confidence_threshold, margin_threshold
                    )
                )
                for prediction in predictions
            )
            for predicted_label in column_labels
        ]
        for true_label in row_labels
    ]
    neutral_accepted = sum(
        prediction.true_label == NEUTRAL_LABEL for prediction in accepted
    )
    class_f1_values: list[float] = []
    for label in EXPECTED_V2_LABELS:
        f1_value = per_class[label]["f1"]
        if not isinstance(f1_value, float):
            raise AbstentionEvaluationError("a computed class metric is invalid")
        class_f1_values.append(f1_value)
    helplessness = per_class[HELPLESSNESS_LABEL]
    return {
        "confidence_threshold": confidence_threshold,
        "margin_threshold": margin_threshold,
        "total_count": len(predictions),
        "accepted_count": accepted_count,
        "abstained_count": len(predictions) - accepted_count,
        "acceptance_rate": _ratio(accepted_count, len(predictions)),
        "accepted_accuracy": _ratio(correct_accepted, accepted_count),
        "accepted_precision": _ratio(correct_accepted, accepted_count),
        "accepted_macro_f1": round(
            sum(class_f1_values) / len(class_f1_values), 6
        ),
        "per_class": per_class,
        "helplessness_precision": helplessness["precision"],
        "helplessness_recall": helplessness["recall"],
        "helplessness_f1": helplessness["f1"],
        "neutral_sample_count": neutral_count,
        "neutral_accepted_count": neutral_accepted,
        "neutral_false_positive_rate": (
            _ratio(neutral_accepted, neutral_count) if neutral_count else None
        ),
        "confusion_matrix": {
            "true_labels": row_labels,
            "predicted_labels": column_labels,
            "matrix": confusion_matrix,
        },
    }


def threshold_grid(
    predictions: Sequence[ScoredEmotionPrediction],
    *,
    confidence_thresholds: Sequence[float] = DEFAULT_CONFIDENCE_THRESHOLDS,
    margin_thresholds: Sequence[float] = DEFAULT_MARGIN_THRESHOLDS,
) -> list[dict[str, object]]:
    """Evaluate every confidence-margin pair over one cached prediction set."""

    if not confidence_thresholds or not margin_thresholds:
        raise AbstentionEvaluationError("threshold grids must not be empty")
    return [
        evaluate_threshold(
            predictions,
            confidence_threshold=confidence_threshold,
            margin_threshold=margin_threshold,
        )
        for confidence_threshold in confidence_thresholds
        for margin_threshold in margin_thresholds
    ]


def calibration_bins(
    predictions: Sequence[ScoredEmotionPrediction],
    *,
    field: str,
    boundaries: Sequence[float],
) -> list[dict[str, object]]:
    """Return accuracy by non-overlapping confidence or margin interval."""

    if field not in {"confidence", "margin"}:
        raise AbstentionEvaluationError("calibration field is unsupported")
    if (
        len(boundaries) < 2
        or boundaries[0] != 0.0
        or boundaries[-1] != 1.0
        or any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in boundaries
        )
        or any(left >= right for left, right in zip(boundaries, boundaries[1:]))
    ):
        raise AbstentionEvaluationError(
            "calibration boundaries must increase from zero to one"
        )
    if not predictions:
        raise AbstentionEvaluationError("at least one scored prediction is required")
    bins: list[dict[str, object]] = []
    for index, (lower, upper) in enumerate(zip(boundaries, boundaries[1:])):
        is_last = index == len(boundaries) - 2
        selected = [
            prediction
            for prediction in predictions
            if lower <= float(getattr(prediction, field))
            and (
                float(getattr(prediction, field)) <= upper
                if is_last
                else float(getattr(prediction, field)) < upper
            )
        ]
        correct = sum(
            prediction.true_label == prediction.predicted_label
            for prediction in selected
        )
        bins.append(
            {
                "lower_inclusive": lower,
                "upper": upper,
                "upper_inclusive": is_last,
                "sample_count": len(selected),
                "accuracy": _ratio(correct, len(selected)),
            }
        )
    return bins


__all__ = [
    "ABSTAIN_LABEL",
    "DEFAULT_CONFIDENCE_BINS",
    "DEFAULT_CONFIDENCE_THRESHOLDS",
    "DEFAULT_MARGIN_BINS",
    "DEFAULT_MARGIN_THRESHOLDS",
    "HELPLESSNESS_LABEL",
    "NEUTRAL_LABEL",
    "AbstentionEvaluationError",
    "ScoredEmotionPrediction",
    "calibration_bins",
    "evaluate_threshold",
    "threshold_grid",
]
