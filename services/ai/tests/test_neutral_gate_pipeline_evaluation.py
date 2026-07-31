from __future__ import annotations

import pytest
from ai.src.remind_ai.evaluation.neutral_gate_pipeline import (
    ScoredPipelinePrediction,
    evaluate_combined_pipeline,
)


def test_combined_pipeline_reports_gate_and_downstream_quality() -> None:
    rows = [
        ScoredPipelinePrediction("neutral", 0.10, None, "기쁨", 0.90, 0.80, 2.0, 4.0),
        ScoredPipelinePrediction("neutral", 0.70, None, "기쁨", 0.40, 0.10, 3.0, 5.0),
        ScoredPipelinePrediction(
            "emotional", 0.90, "무기력", "무기력", 0.80, 0.60, 2.0, 8.0
        ),
        ScoredPipelinePrediction(
            "emotional", 0.80, "불안", "슬픔", 0.70, 0.40, 2.5, 7.0
        ),
        ScoredPipelinePrediction(
            "emotional", 0.30, "슬픔", "슬픔", 0.90, 0.80, 1.5, 6.0
        ),
    ]
    result = evaluate_combined_pipeline(rows, gate_threshold=0.50)
    assert result["gate"]["neutral_false_positive_rate"] == pytest.approx(0.5)
    assert result["gate"]["emotional_retention"] == pytest.approx(2 / 3)
    assert result["combined_neutral_false_positive_rate"] == 0.0
    assert result["accepted_emotional_rate"] == pytest.approx(2 / 3)
    assert result["accepted_precision"] == 0.5
    assert result["lethargy_recall"] == 1.0
    assert result["latency_ms"]["gate_plus_coarse_p95"] == 10.0
