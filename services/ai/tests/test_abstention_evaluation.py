from __future__ import annotations

import pytest

from ai.src.remind_ai.evaluation.abstention import (
    AbstentionEvaluationError,
    ScoredEmotionPrediction,
    calibration_bins,
    evaluate_threshold,
    threshold_grid,
)


def scored_predictions() -> list[ScoredEmotionPrediction]:
    return [
        ScoredEmotionPrediction("분노", "분노", 0.90, 0.40),
        ScoredEmotionPrediction("무기력", "무기력", 0.80, 0.20),
        ScoredEmotionPrediction("무기력", "슬픔", 0.70, 0.20),
        ScoredEmotionPrediction("슬픔", "슬픔", 0.60, 0.10),
        ScoredEmotionPrediction("중립", "기쁨", 0.80, 0.30),
        ScoredEmotionPrediction("중립", "분노", 0.40, 0.05),
    ]


def test_threshold_metrics_include_coverage_class_and_neutral_quality() -> None:
    metrics = evaluate_threshold(
        scored_predictions(),
        confidence_threshold=0.65,
        margin_threshold=0.15,
    )

    assert metrics["total_count"] == 6
    assert metrics["accepted_count"] == 4
    assert metrics["abstained_count"] == 2
    assert metrics["acceptance_rate"] == pytest.approx(4 / 6, abs=1e-6)
    assert metrics["accepted_accuracy"] == 0.5
    assert metrics["accepted_precision"] == 0.5
    assert metrics["accepted_macro_f1"] == pytest.approx(0.277778)
    assert metrics["helplessness_precision"] == 1.0
    assert metrics["helplessness_recall"] == 0.5
    assert metrics["helplessness_f1"] == pytest.approx(0.666667)
    assert metrics["neutral_sample_count"] == 2
    assert metrics["neutral_false_positive_rate"] == 0.5
    assert metrics["confusion_matrix"] == {
        "true_labels": ["분노", "기쁨", "불안", "당황", "슬픔", "무기력", "중립"],
        "predicted_labels": [
            "분노",
            "기쁨",
            "불안",
            "당황",
            "슬픔",
            "무기력",
            "abstain",
        ],
        "matrix": [
            [1, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 1],
            [0, 0, 0, 0, 1, 1, 0],
            [0, 1, 0, 0, 0, 0, 1],
        ],
    }


def test_no_accepted_samples_return_zero_metrics_without_division_errors() -> None:
    metrics = evaluate_threshold(
        scored_predictions(),
        confidence_threshold=1.0,
        margin_threshold=1.0,
    )

    assert metrics["accepted_count"] == 0
    assert metrics["acceptance_rate"] == 0.0
    assert metrics["accepted_precision"] == 0.0
    assert metrics["accepted_macro_f1"] == 0.0
    assert metrics["helplessness_precision"] == 0.0
    assert metrics["neutral_false_positive_rate"] == 0.0


def test_missing_neutral_samples_are_reported_as_unavailable() -> None:
    metrics = evaluate_threshold(
        [ScoredEmotionPrediction("분노", "분노", 0.9, 0.4)],
        confidence_threshold=0.65,
        margin_threshold=0.15,
    )

    assert metrics["neutral_sample_count"] == 0
    assert metrics["neutral_accepted_count"] == 0
    assert metrics["neutral_false_positive_rate"] is None


def test_threshold_grid_reuses_records_for_every_pair() -> None:
    results = threshold_grid(
        scored_predictions(),
        confidence_thresholds=(0.5, 0.7),
        margin_thresholds=(0.1, 0.2),
    )

    assert [
        (result["confidence_threshold"], result["margin_threshold"])
        for result in results
    ] == [(0.5, 0.1), (0.5, 0.2), (0.7, 0.1), (0.7, 0.2)]


def test_calibration_bins_include_upper_bound_only_in_last_interval() -> None:
    predictions = [
        ScoredEmotionPrediction("분노", "분노", 0.5, 0.1),
        ScoredEmotionPrediction("슬픔", "분노", 1.0, 1.0),
    ]

    bins = calibration_bins(
        predictions,
        field="confidence",
        boundaries=(0.0, 0.5, 1.0),
    )

    assert bins == [
        {
            "lower_inclusive": 0.0,
            "upper": 0.5,
            "upper_inclusive": False,
            "sample_count": 0,
            "accuracy": 0.0,
        },
        {
            "lower_inclusive": 0.5,
            "upper": 1.0,
            "upper_inclusive": True,
            "sample_count": 2,
            "accuracy": 0.5,
        },
    ]


@pytest.mark.parametrize(
    ("confidence", "margin"),
    [
        (-0.1, 0.0),
        (1.1, 0.0),
        (float("nan"), 0.0),
        (0.5, 0.6),
    ],
)
def test_scored_prediction_rejects_invalid_probabilities(
    confidence: float, margin: float
) -> None:
    with pytest.raises(AbstentionEvaluationError):
        ScoredEmotionPrediction("분노", "분노", confidence, margin)
