"""Synthetic-only tests for TF-IDF training, evaluation, and safe artifacts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from ai.src.remind_ai.data.emotion_dataset import EmotionSample, sample_from_record
from ai.src.remind_ai.data.emotion_taxonomy_v2 import (
    EXPECTED_V2_LABELS,
    source_text_sha256,
)
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


def _v2_records(profile_start: int, profile_stop: int) -> list[dict[str, object]]:
    fine_labels = ("E10", "E60", "E30", "E50", "E20", "E25")
    records: list[dict[str, object]] = []
    for profile in range(profile_start, profile_stop):
        for label_index, label in enumerate(fine_labels):
            index = profile * 10 + label_index
            record = _record(index, label)
            talk = record["talk"]
            assert isinstance(talk, dict)
            talk_id = talk["id"]
            assert isinstance(talk_id, dict)
            talk_id["profile-id"] = f"PRIVATE-V2-PROFILE-{profile}"
            content = talk["content"]
            assert isinstance(content, dict)
            content["HS01"] = f"PRIVATE V2 UNIQUE TEXT {profile} {label_index}"
            records.append(record)
    return records


def _write_v2_manifest(
    path: Path,
    train_records: list[dict[str, object]],
    validation_records: list[dict[str, object]],
) -> None:
    decisions: list[dict[str, object]] = []
    for official_split, records in (
        ("official_train", train_records),
        ("official_validation", validation_records),
    ):
        for record in records:
            profile = record["profile"]
            assert isinstance(profile, dict)
            emotion = profile["emotion"]
            assert isinstance(emotion, dict)
            if emotion["type"] != "E40":
                continue
            talk = record["talk"]
            assert isinstance(talk, dict)
            identifiers = talk["id"]
            assert isinstance(identifiers, dict)
            sample = sample_from_record(record, official_split)
            decisions.append(
                {
                    "official_split": official_split,
                    "profile_id": identifiers["profile-id"],
                    "talk_id": identifiers["talk-id"],
                    "source_fine_label": "E40",
                    "source_text_sha256": source_text_sha256(sample),
                    "decision": "relabel",
                    "label": "무기력",
                    "review_status": "approved",
                }
            )
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "label_set_version": "remind-coarse-v2",
                "dataset_release_id": "synthetic-v2-release-001",
                "annotation_revision": 1,
                "records": decisions,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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


def test_annotation_manifest_requires_v2_label_set(
    training_script: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_json = tmp_path / "train.json"
    validation_json = tmp_path / "validation.json"
    manifest = tmp_path / "private-review.json"
    output_dir = tmp_path / "output"
    train_json.write_text(
        json.dumps([_record(1, "A"), _record(2, "B")]), encoding="utf-8"
    )
    validation_json.write_text(
        json.dumps([_record(3, "A"), _record(4, "B")]), encoding="utf-8"
    )
    manifest.write_text("{}", encoding="utf-8")

    code = training_script.main(
        [
            "--train-json",
            str(train_json),
            "--validation-json",
            str(validation_json),
            "--output-dir",
            str(output_dir),
            "--annotation-manifest",
            str(manifest),
        ]
    )

    assert code == 2
    assert "only be used with remind-coarse-v2" in capsys.readouterr().err
    assert not output_dir.exists()


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


def test_coarse_v2_uses_deterministic_fine_mapping_and_exact_private_split(
    training_script: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_json = tmp_path / "v2_train.json"
    validation_json = tmp_path / "v2_validation.json"
    output_dir = tmp_path / "tfidf-v2"
    train_records = _v2_records(0, 3)
    validation_records = _v2_records(3, 6)
    train_json.write_text(
        json.dumps(train_records, ensure_ascii=False), encoding="utf-8"
    )
    validation_json.write_text(
        json.dumps(validation_records, ensure_ascii=False), encoding="utf-8"
    )
    code = training_script.main(
        [
            "--train-json",
            str(train_json),
            "--validation-json",
            str(validation_json),
            "--output-dir",
            str(output_dir),
            "--label-set",
            "remind-coarse-v2",
            "--dataset-release-id",
            "synthetic-v2-release-001",
            "--min-df",
            "1",
            "--candidate-count",
            "20",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    labels = json.loads((output_dir / "label_classes.json").read_text(encoding="utf-8"))
    run_config = json.loads(
        (output_dir / "run_config.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (output_dir / "preparation_report.json").read_text(encoding="utf-8")
    )
    assert labels["classes"] == list(EXPECTED_V2_LABELS)
    assert labels["label_field"] == "deterministic_remind_coarse_v2"
    assert "상처" not in labels["classes"]
    assert run_config["model_version"] == "tfidf-logreg-remind-coarse-v2"
    assert run_config["label_field"] == "deterministic_remind_coarse_v2"
    assert run_config["dataset_release_id"] == "synthetic-v2-release-001"
    assert run_config["annotation_revision"] is None
    assert report["prepared_class_counts"]["무기력"] == 6
    assert report["fine_label_overrides"] == {
        "E25": "무기력",
        "E28": "무기력",
    }
    assert (output_dir / "private" / "split_assignment.json").is_file()
    for name in (
        "classification_report.json",
        "confusion_matrix.json",
        "evaluation_summary.json",
        "inference_benchmark.json",
        "training_summary.json",
        "model_metadata.json",
        "label_policy_summary.json",
    ):
        assert (output_dir / name).is_file()
    shareable = "".join(
        path.read_text(encoding="utf-8")
        for path in output_dir.iterdir()
        if path.is_file() and path.suffix in {".json", ".md"}
    )
    assert "PRIVATE-V2-PROFILE" not in shareable
    assert "PRIVATE-TALK" not in shareable
    assert str(train_json) not in shareable
    assert "PRIVATE" not in captured.out + captured.err
