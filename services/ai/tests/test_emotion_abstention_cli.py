from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = AI_SERVICE_ROOT / "scripts" / "evaluate_emotion_abstention.py"


@pytest.fixture(scope="module")
def evaluation_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_emotion_abstention_evaluation_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_predictions(path: Path) -> None:
    rows = [
        {
            "sample_index": 0,
            "true_label": "분노",
            "predicted_label": "분노",
            "confidence": 0.9,
            "margin": 0.4,
        },
        {
            "sample_index": 1,
            "true_label": "무기력",
            "predicted_label": "슬픔",
            "confidence": 0.6,
            "margin": 0.1,
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_cli_reuses_scored_predictions_and_writes_all_reports(
    evaluation_script: ModuleType, tmp_path: Path
) -> None:
    predictions = tmp_path / "scores.jsonl"
    output_dir = tmp_path / "evaluation"
    _write_predictions(predictions)

    result = evaluation_script.run(
        evaluation_script._parser().parse_args(
            [
                "--scored-predictions",
                str(predictions),
                "--dataset-identifier",
                "synthetic-v1",
                "--model-version",
                "model-v2",
                "--output-dir",
                str(output_dir),
            ]
        )
    )

    assert result["metadata"] == {
        "model_version": "model-v2",
        "taxonomy_version": "remind-coarse-v2",
        "dataset_identifier": "synthetic-v1",
        "source": "scored_predictions",
        "sample_count": 2,
        "neutral_evaluation_available": False,
        "threshold_grid": {
            "confidence": [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8],
            "margin": [0.05, 0.1, 0.15, 0.2, 0.25],
        },
    }
    assert len(result["grid"]) == 35
    assert {
        path.name for path in output_dir.iterdir()
    } == {
        "confidence_bins.json",
        "current_threshold_metrics.json",
        "margin_bins.json",
        "threshold_grid.csv",
        "threshold_grid.json",
    }
    current = json.loads(
        (output_dir / "current_threshold_metrics.json").read_text(encoding="utf-8")
    )
    assert current["metrics"]["accepted_count"] == 1
    assert current["metrics"]["neutral_false_positive_rate"] is None
    assert current["metadata"]["dataset_identifier"] == "synthetic-v1"


def test_cli_rejects_legacy_predictions_without_confidence_and_margin(
    evaluation_script: ModuleType, tmp_path: Path
) -> None:
    predictions = tmp_path / "legacy.jsonl"
    predictions.write_text(
        json.dumps(
            {"true_label": "분노", "predicted_label": "분노"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        evaluation_script.EmotionAbstentionCliError,
        match="record is invalid",
    ):
        evaluation_script._load_scored_predictions(predictions)


def test_calibration_loader_accepts_review_metadata_but_requires_product_turns(
    evaluation_script: ModuleType, tmp_path: Path
) -> None:
    calibration = tmp_path / "calibration.jsonl"
    calibration.write_text(
        json.dumps(
            {
                "id": "cal-v1-001",
                "turns": ["오늘은 특별한 일이 없었어.", "평소처럼 하루를 보냈어."],
                "label": "중립",
                "difficulty": "medium",
                "boundary": "감정-중립",
                "reviewed_by": ["reviewer_1", "reviewer_2"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    inputs = evaluation_script._load_calibration_inputs(calibration)

    assert len(inputs) == 1
    assert inputs[0][0] == "중립"
    assert inputs[0][1].hs01 == "오늘은 특별한 일이 없었어."
    assert inputs[0][1].hs02 == "평소처럼 하루를 보냈어."


def test_calibration_loader_rejects_single_turn_records(
    evaluation_script: ModuleType, tmp_path: Path
) -> None:
    calibration = tmp_path / "calibration.jsonl"
    calibration.write_text(
        json.dumps(
            {"id": "cal-v1-001", "turns": ["한 문장"], "label": "중립"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        evaluation_script.EmotionAbstentionCliError,
        match="record is invalid",
    ):
        evaluation_script._load_calibration_inputs(calibration)
