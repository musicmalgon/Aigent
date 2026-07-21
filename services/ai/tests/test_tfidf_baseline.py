"""Synthetic-only tests for TF-IDF training, evaluation, and safe artifacts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from ai.src.remind_ai.data.emotion_dataset import EmotionSample
from ai.src.remind_ai.models.tfidf_baseline import (
    BaselineConfig,
    BaselineError,
    evaluate_model,
    fit_model,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "ai" / "scripts" / "train_tfidf_baseline.py"


def _samples() -> list[EmotionSample]:
    return [
        EmotionSample(
            "sun bright",
            "SYNTH_A",
            "PRIVATE-TALK-1",
            "PRIVATE-GROUP-1",
            "official_train",
        ),
        EmotionSample(
            "sun warm", "SYNTH_A", "PRIVATE-TALK-2", "PRIVATE-GROUP-2", "official_train"
        ),
        EmotionSample(
            "rain dark",
            "SYNTH_B",
            "PRIVATE-TALK-3",
            "PRIVATE-GROUP-3",
            "official_train",
        ),
        EmotionSample(
            "rain cold",
            "SYNTH_B",
            "PRIVATE-TALK-4",
            "PRIVATE-GROUP-4",
            "official_train",
        ),
    ]


def test_vectorizer_fits_only_train_and_reports_macro_f1() -> None:
    train = _samples()
    fitted = fit_model(train, BaselineConfig("word", "word", min_df=1))
    metrics = evaluate_model(fitted, train)
    vocabulary = set(fitted.vectorizer.get_feature_names_out())
    assert "validationonlytoken" not in vocabulary
    macro_f1 = metrics["macro_f1"]
    assert isinstance(macro_f1, float)
    assert 0.0 <= macro_f1 <= 1.0
    assert "predicted_class_distribution" in metrics


def test_single_class_training_fails() -> None:
    with pytest.raises(BaselineError):
        fit_model(_samples()[:2], BaselineConfig("word", "word", min_df=1))


@pytest.fixture(scope="module")
def training_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_tfidf_training_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _record(index: int, label: str) -> dict[str, object]:
    return {
        "profile": {"emotion": {"type": label, "emotion-id": "IGNORED"}},
        "talk": {
            "content": {
                "HS01": f"PRIVATE SOURCE TEXT {index}",
                "HS02": f"PRIVATE TURN TEXT {label}",
                "HS03": None,
                "SS01": "PRIVATE SYSTEM TEXT",
            },
            "id": {
                "talk-id": f"PRIVATE-TALK-{index}",
                "profile-id": f"PRIVATE-PROFILE-{index}",
            },
        },
    }


def test_training_script_writes_safe_aggregate_artifacts(
    training_script: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_json = tmp_path / "private_train.json"
    validation_json = tmp_path / "private_validation.json"
    output_dir = tmp_path / "output"
    records = [
        _record(index, "SYNTH_A" if index % 2 else "SYNTH_B") for index in range(8)
    ]
    train_json.write_text(json.dumps(records[:4]), encoding="utf-8")
    validation_json.write_text(json.dumps(records[4:]), encoding="utf-8")
    code = training_script.main(
        [
            "--train-json",
            str(train_json),
            "--validation-json",
            str(validation_json),
            "--output-dir",
            str(output_dir),
            "--min-df",
            "1",
            "--candidate-count",
            "20",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    for name in (
        "split_summary.json",
        "validation_metrics.json",
        "test_metrics.json",
        "official_validation_metrics.json",
        "model.joblib",
        "vectorizer.joblib",
        "label_classes.json",
        "run_config.json",
        "README.md",
    ):
        assert (output_dir / name).is_file()
    serialized = (
        "".join(path.read_text(encoding="utf-8") for path in output_dir.glob("*.json"))
        + (output_dir / "README.md").read_text(encoding="utf-8")
        + captured.out
        + captured.err
    )
    assert "PRIVATE SOURCE TEXT" not in serialized
    assert "PRIVATE-TALK-" not in serialized
    assert "PRIVATE-PROFILE-" not in serialized
    assert str(train_json) not in serialized


def test_relative_paths_fail_without_echoing_them(
    training_script: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = training_script.main(
        [
            "--train-json",
            "private.json",
            "--validation-json",
            "valid.json",
            "--output-dir",
            "out",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "private.json" not in captured.err


def test_split_failure_writes_safe_diagnostics(
    training_script: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_json = tmp_path / "private_train.json"
    validation_json = tmp_path / "private_validation.json"
    output_dir = tmp_path / "failure_output"
    train_json.write_text(json.dumps([_record(1, "SYNTH_A")]), encoding="utf-8")
    validation_json.write_text(json.dumps([_record(2, "SYNTH_B")]), encoding="utf-8")
    code = training_script.main(
        [
            "--train-json",
            str(train_json),
            "--validation-json",
            str(validation_json),
            "--output-dir",
            str(output_dir),
        ]
    )
    captured = capsys.readouterr()
    diagnostics = output_dir / "split_failure_diagnostics.json"
    assert code == 2
    assert diagnostics.is_file()
    serialized = diagnostics.read_text(encoding="utf-8") + captured.err
    assert "PRIVATE" not in serialized
    assert str(train_json) not in serialized
