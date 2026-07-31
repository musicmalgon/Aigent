from __future__ import annotations

import pytest
from ai.src.remind_ai.evaluation.neutral_gate import (
    NeutralGateEvaluationError,
    ScoredGatePrediction,
    evaluate_gate_threshold,
    select_gate_threshold,
    threshold_sweep,
)


def _predictions() -> list[ScoredGatePrediction]:
    return [
        ScoredGatePrediction("neutral", 0.05),
        ScoredGatePrediction("neutral", 0.20),
        ScoredGatePrediction("neutral", 0.70),
        ScoredGatePrediction("emotional", 0.90),
        ScoredGatePrediction("emotional", 0.80),
        ScoredGatePrediction("emotional", 0.40),
    ]


def test_metrics_report_fpr_retention_and_confusion_matrix() -> None:
    result = evaluate_gate_threshold(_predictions(), threshold=0.5)
    assert result["neutral_false_positive_rate"] == pytest.approx(1 / 3)
    assert result["emotional_retention"] == pytest.approx(2 / 3)
    assert result["confusion_matrix"]["matrix"] == [[2, 1], [1, 2]]


def test_emotional_probability_at_threshold_is_accepted() -> None:
    result = evaluate_gate_threshold(
        [
            ScoredGatePrediction("neutral", 0.49),
            ScoredGatePrediction("emotional", 0.50),
        ],
        threshold=0.50,
    )
    assert result["confusion_matrix"]["matrix"] == [[1, 0], [0, 1]]


def test_selection_uses_calibration_guards() -> None:
    predictions = [
        *[ScoredGatePrediction("neutral", 0.05) for _ in range(19)],
        ScoredGatePrediction("neutral", 0.55),
        *[ScoredGatePrediction("emotional", 0.90) for _ in range(19)],
        ScoredGatePrediction("emotional", 0.45),
    ]
    rows = threshold_sweep(predictions, thresholds=(0.4, 0.5, 0.6))
    selected = select_gate_threshold(rows)
    assert selected["passes_minimum_guards"] is True
    assert selected["threshold"] == 0.4


def test_selection_fails_when_no_threshold_is_safe() -> None:
    rows = threshold_sweep(_predictions(), thresholds=(0.5,))
    with pytest.raises(NeutralGateEvaluationError, match="no threshold"):
        select_gate_threshold(rows)
