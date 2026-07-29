"""Synthetic, network-free tests for the Transformer baseline CLI."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from ai.src.remind_ai.data.emotion_dataset import load_json_samples
from ai.src.remind_ai.data.emotion_label_mapping import (
    load_emotion_label_mapping,
)
from ai.src.remind_ai.data.emotion_taxonomy_v2 import (
    EXPECTED_V2_LABELS,
    load_emotion_label_policy_v2,
    prepare_remind_coarse_v2,
)
from ai.src.remind_ai.data.group_split import select_group_safe_split
from ai.src.remind_ai.data.private_split_assignment import (
    write_private_split_assignment,
)

torch = pytest.importorskip("torch")


AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = AI_SERVICE_ROOT / "scripts" / "train_transformer_baseline.py"


@pytest.fixture(scope="module")
def transformer_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_transformer_training_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TinyTokenizer:
    sep_token = "[SEP]"

    def __call__(self, text: str, **kwargs: Any) -> dict[str, list[int]]:
        max_length = int(kwargs["max_length"])
        size = min(max(2, len(text.split())), max_length)
        return {"input_ids": list(range(size)), "attention_mask": [1] * size}

    def save_pretrained(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tokenizer_config.json").write_text("{}", encoding="utf-8")


class TinyClassifier(torch.nn.Module):  # type: ignore[name-defined]
    def __init__(self, classes: int) -> None:
        super().__init__()
        self.bias = torch.nn.Parameter(torch.zeros(classes))

    def forward(self, input_ids: Any, attention_mask: Any, labels: Any = None) -> Any:
        del attention_mask
        logits = self.bias.unsqueeze(0).repeat(input_ids.shape[0], 1)
        loss = (
            torch.nn.functional.cross_entropy(logits, labels)
            if labels is not None
            else None
        )
        return SimpleNamespace(logits=logits, loss=loss)

    def save_pretrained(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        torch.save(self.state_dict(), directory / "pytorch_model.bin")


def _collate(features: list[dict[str, Any]]) -> dict[str, Any]:
    max_size = max(len(feature["input_ids"]) for feature in features)
    ids: list[list[int]] = []
    masks: list[list[int]] = []
    labels: list[int] = []
    for feature in features:
        padding = max_size - len(feature["input_ids"])
        ids.append([*feature["input_ids"], *([0] * padding)])
        masks.append([*feature["attention_mask"], *([0] * padding)])
        labels.append(feature["labels"])
    return {
        "input_ids": torch.tensor(ids),
        "attention_mask": torch.tensor(masks),
        "labels": torch.tensor(labels),
    }


def _records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for profile in range(8):
        for label_index, label in enumerate(("SYNTH_A", "SYNTH_B")):
            records.append(
                {
                    "profile": {
                        "emotion": {"type": label, "emotion-id": "PRIVATE-IGNORED"}
                    },
                    "talk": {
                        "content": {
                            "HS01": f"PRIVATE USER TEXT {profile} {label_index}",
                            "HS02": "PRIVATE SECOND TURN",
                            "HS03": None,
                            "SS01": "PRIVATE SYSTEM RESPONSE",
                        },
                        "id": {
                            "talk-id": f"PRIVATE-RAW-{label_index}",
                            "profile-id": f"PRIVATE-PROFILE-{profile}",
                        },
                    },
                }
            )
    return records


def _coarse_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    fine_labels = ("E60", "E30", "E50", "E10", "E20", "E40")
    for profile in range(8):
        for label_index, label in enumerate(fine_labels):
            records.append(
                {
                    "profile": {"emotion": {"type": label}},
                    "talk": {
                        "content": {
                            "HS01": f"COARSE USER TEXT {profile} {label_index}",
                            "HS02": "COARSE SECOND TURN",
                            "HS03": "",
                        },
                        "id": {
                            "talk-id": f"COARSE-RAW-{profile}-{label_index}",
                            "profile-id": f"COARSE-PROFILE-{profile}",
                        },
                    },
                }
            )
    return records


def _prepare_inputs(
    module: ModuleType, tmp_path: Path
) -> tuple[Path, Path, Path, Path]:
    train_path = tmp_path / "private_training.json"
    validation_path = tmp_path / "private_validation.json"
    tfidf_dir = tmp_path / "tfidf"
    output_dir = tmp_path / "transformer"
    records = _records()
    train_path.write_text(json.dumps(records[:8]), encoding="utf-8")
    validation_path.write_text(json.dumps(records[8:]), encoding="utf-8")
    samples = [
        *load_json_samples(train_path, "official_train"),
        *load_json_samples(validation_path, "official_validation"),
    ]
    split = select_group_safe_split(samples, random_state=42, candidate_count=200)
    partitions = {
        name: split.samples_for(samples, name)
        for name in ("train", "validation", "test")
    }
    summary = module._split_summary(samples, partitions, split)
    summary["random_state"] = 42
    summary["requested_candidate_count"] = 200
    tfidf_dir.mkdir()
    (tfidf_dir / "run_config.json").write_text(
        json.dumps({"random_state": 42, "candidate_count": 200}), encoding="utf-8"
    )
    (tfidf_dir / "split_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (tfidf_dir / "validation_metrics.json").write_text(
        json.dumps({"selected_model": "char_tfidf"}), encoding="utf-8"
    )
    (tfidf_dir / "test_metrics.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "accuracy": 0.333624,
                    "macro_f1": 0.317472,
                    "weighted_f1": 0.342856,
                }
            }
        ),
        encoding="utf-8",
    )
    return train_path, validation_path, tfidf_dir, output_dir


def _prepare_coarse_inputs(
    module: ModuleType, tmp_path: Path
) -> tuple[Path, Path, Path, Path]:
    train_path = tmp_path / "coarse_training.json"
    validation_path = tmp_path / "coarse_validation.json"
    tfidf_dir = tmp_path / "tfidf-coarse-source"
    output_dir = tmp_path / "transformer-coarse"
    records = _coarse_records()
    train_path.write_text(json.dumps(records[:24]), encoding="utf-8")
    validation_path.write_text(json.dumps(records[24:]), encoding="utf-8")
    samples = [
        *load_json_samples(train_path, "official_train"),
        *load_json_samples(validation_path, "official_validation"),
    ]
    split = select_group_safe_split(samples, random_state=42, candidate_count=200)
    partitions = {
        name: split.samples_for(samples, name)
        for name in ("train", "validation", "test")
    }
    summary = module._split_summary(samples, partitions, split)
    summary["random_state"] = 42
    summary["requested_candidate_count"] = 200
    tfidf_dir.mkdir()
    (tfidf_dir / "run_config.json").write_text(
        json.dumps({"random_state": 42, "candidate_count": 200}), encoding="utf-8"
    )
    (tfidf_dir / "split_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (tfidf_dir / "validation_metrics.json").write_text(
        json.dumps({"selected_model": "char_tfidf"}), encoding="utf-8"
    )
    (tfidf_dir / "test_metrics.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "accuracy": 0.397205,
                    "macro_f1": 0.376819,
                    "weighted_f1": 0.410490,
                }
            }
        ),
        encoding="utf-8",
    )
    return train_path, validation_path, tfidf_dir, output_dir


def _prepare_v2_inputs(
    module: ModuleType, tmp_path: Path
) -> tuple[Path, Path, Path, Path, Path]:
    train_path = tmp_path / "v2_training.json"
    validation_path = tmp_path / "v2_validation.json"
    annotation_path = tmp_path / "private_v2_annotations.json"
    tfidf_dir = tmp_path / "tfidf-v2-source"
    output_dir = tmp_path / "transformer-v2"
    fine_labels = ("E10", "E60", "E30", "E50", "E20", "E25")
    records: list[dict[str, object]] = []
    for profile in range(6):
        for label_index, label in enumerate(fine_labels):
            talk_id = f"PRIVATE-V2-TALK-{profile}-{label_index}"
            profile_id = f"PRIVATE-V2-PROFILE-{profile}"
            record: dict[str, object] = {
                "profile": {"emotion": {"type": label}},
                "talk": {
                    "content": {
                        "HS01": (f"PRIVATE V2 UNIQUE {profile} {label_index}"),
                        "HS02": f"PRIVATE V2 TURN {label_index}",
                        "HS03": None,
                    },
                    "id": {
                        "talk-id": talk_id,
                        "profile-id": profile_id,
                    },
                },
            }
            records.append(record)
    train_records = records[: 3 * len(fine_labels)]
    validation_records = records[3 * len(fine_labels) :]
    train_path.write_text(
        json.dumps(train_records, ensure_ascii=False), encoding="utf-8"
    )
    validation_path.write_text(
        json.dumps(validation_records, ensure_ascii=False), encoding="utf-8"
    )
    samples = [
        *load_json_samples(train_path, "official_train"),
        *load_json_samples(validation_path, "official_validation"),
    ]
    policy = load_emotion_label_policy_v2(
        AI_SERVICE_ROOT / "config" / "emotion_label_policy_v2.json"
    )
    prepared = prepare_remind_coarse_v2(
        samples,
        load_emotion_label_mapping(
            AI_SERVICE_ROOT / "config" / "emotion_label_mapping.json"
        ),
        policy,
        dataset_release_id="synthetic-v2-release-001",
    )
    model_samples = list(prepared.samples)
    split = select_group_safe_split(
        model_samples,
        random_state=42,
        candidate_count=20,
        require_evaluation_class_coverage=True,
        require_normalized_text_isolation=True,
    )
    partitions = {
        name: split.samples_for(model_samples, name)
        for name in ("train", "validation", "test")
    }
    summary = module._split_summary(model_samples, partitions, split)
    summary["random_state"] = 42
    summary["requested_candidate_count"] = 20
    tfidf_dir.mkdir()
    (tfidf_dir / "run_config.json").write_text(
        json.dumps(
            {
                "model_version": "tfidf-logreg-remind-coarse-v2",
                "label_set_version": "remind-coarse-v2",
                "dataset_release_id": "synthetic-v2-release-001",
                "annotation_revision": None,
                "common_private_split_assignment": ("private/split_assignment.json"),
                "split_random_state": 42,
                "candidate_count": 20,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tfidf_dir / "split_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )
    (tfidf_dir / "label_classes.json").write_text(
        json.dumps(
            {
                "label_set_version": "remind-coarse-v2",
                "classes": list(EXPECTED_V2_LABELS),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    synthetic_metrics = {
        "accuracy": 0.5,
        "macro_f1": 0.4,
        "weighted_f1": 0.45,
    }
    (tfidf_dir / "validation_metrics.json").write_text(
        json.dumps(
            {
                "selected_model": "char_tfidf",
                "experiments": {"char_tfidf": {"metrics": synthetic_metrics}},
            }
        ),
        encoding="utf-8",
    )
    (tfidf_dir / "test_metrics.json").write_text(
        json.dumps({"metrics": synthetic_metrics}), encoding="utf-8"
    )
    (tfidf_dir / "training_summary.json").write_text(
        json.dumps({"total_elapsed_seconds": 1.0}), encoding="utf-8"
    )
    (tfidf_dir / "inference_benchmark.json").write_text(
        json.dumps(
            {
                "protocol_version": "emotion-inference-benchmark-v1",
                "device": "cpu",
                "batches": [],
            }
        ),
        encoding="utf-8",
    )
    write_private_split_assignment(
        (tfidf_dir / "private" / "split_assignment.json").resolve(),
        model_samples,
        split,
        label_set_version="remind-coarse-v2",
        random_state=42,
        candidate_count=20,
    )
    return (
        train_path,
        validation_path,
        annotation_path,
        tfidf_dir,
        output_dir,
    )


def test_dry_run_reuses_split_and_writes_safe_artifacts(
    transformer_script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_path, validation_path, tfidf_dir, output_dir = _prepare_inputs(
        transformer_script, tmp_path
    )
    tokenizer = TinyTokenizer()
    monkeypatch.setattr(transformer_script, "load_tokenizer", lambda name: tokenizer)
    monkeypatch.setattr(
        transformer_script,
        "load_classifier",
        lambda config, labels: TinyClassifier(len(labels.classes)),
    )
    monkeypatch.setattr(
        transformer_script, "create_data_collator", lambda value: _collate
    )
    code = transformer_script.main(
        [
            "--train-json",
            str(train_path),
            "--validation-json",
            str(validation_path),
            "--tfidf-output-dir",
            str(tfidf_dir),
            "--output-dir",
            str(output_dir),
            "--model-name",
            "synthetic-model",
            "--device",
            "cpu",
            "--dry-run",
            "--dry-run-samples",
            "4",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    for name in (
        "split_summary.json",
        "label_classes.json",
        "run_config.json",
        "dry_run_summary.json",
        "comparison.json",
        "README.md",
    ):
        assert (output_dir / name).is_file()
    summary = json.loads(
        (output_dir / "split_summary.json").read_text(encoding="utf-8")
    )
    assert summary["split_reused_from_tfidf"] is True
    for category in (
        "profile_id_overlap_count",
        "conversation_key_overlap_count",
        "normalized_text_overlap_count",
    ):
        assert all(value == 0 for value in summary["overlap_checks"][category].values())
    serialized = (
        "".join(
            path.read_text(encoding="utf-8")
            for path in output_dir.iterdir()
            if path.is_file()
        )
        + captured.out
        + captured.err
    )
    assert "PRIVATE USER TEXT" not in serialized
    assert "PRIVATE-PROFILE" not in serialized
    assert "PRIVATE-RAW" not in serialized
    assert str(train_path) not in serialized
    assert not (output_dir / "test_metrics.json").exists()


def test_coarse_dry_run_uses_six_labels_and_isolated_output(
    transformer_script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    train_path, validation_path, tfidf_dir, output_dir = _prepare_coarse_inputs(
        transformer_script, tmp_path
    )
    output_dir.mkdir()
    sentinel = output_dir / "existing-fine-output.sentinel"
    sentinel.write_text("do not overwrite", encoding="utf-8")
    tokenizer = TinyTokenizer()
    classifier_sizes: list[int] = []

    monkeypatch.setattr(transformer_script, "load_tokenizer", lambda name: tokenizer)

    def load_classifier(config: Any, labels: Any) -> TinyClassifier:
        del config
        classifier_sizes.append(len(labels.classes))
        return TinyClassifier(len(labels.classes))

    monkeypatch.setattr(transformer_script, "load_classifier", load_classifier)
    monkeypatch.setattr(
        transformer_script, "create_data_collator", lambda value: _collate
    )
    code = transformer_script.main(
        [
            "--train-json",
            str(train_path),
            "--validation-json",
            str(validation_path),
            "--tfidf-output-dir",
            str(tfidf_dir),
            "--output-dir",
            str(output_dir),
            "--model-name",
            "synthetic-model",
            "--device",
            "cpu",
            "--label-level",
            "coarse",
            "--disable-progress-bar",
            "--dry-run",
            "--dry-run-samples",
            "6",
        ]
    )
    assert code == 0
    assert classifier_sizes == [6]
    assert sentinel.read_text(encoding="utf-8") == "do not overwrite"
    dry_output = output_dir / "dry-run"
    for name in (
        "split_summary.json",
        "label_classes.json",
        "label_mapping.json",
        "mapping_validation.json",
        "run_config.json",
        "dry_run_summary.json",
        "comparison_with_fine_baseline.json",
        "experiment_summary.md",
        "README.md",
    ):
        assert (dry_output / name).is_file()
    labels = json.loads((dry_output / "label_classes.json").read_text(encoding="utf-8"))
    assert labels["classes"] == ["기쁨", "불안", "당황", "분노", "슬픔", "상처"]
    report = json.loads(
        (dry_output / "mapping_validation.json").read_text(encoding="utf-8")
    )
    assert report["coarse_label_count"] == 6
    assert report["original_sample_count"] == 48
    assert report["mapped_sample_count"] == 48
    assert report["sample_count_preserved"] is True
    summary = json.loads(
        (dry_output / "dry_run_summary.json").read_text(encoding="utf-8")
    )
    assert summary["model_classifier_num_labels"] == 6
    assert summary["smoke_backward_completed"] is True
    assert summary["temporary_checkpoint_saved_and_reloaded"] is True
    assert summary["progress_bar_enabled"] is False
    assert not (dry_output / "checkpoints").exists()
    run_config = json.loads(
        (dry_output / "run_config.json").read_text(encoding="utf-8")
    )
    assert run_config["model_version"] == "klue-roberta-coarse-v1"
    assert run_config["max_length"] == 128


def test_coarse_mode_rejects_max_length_outside_inference_contract(
    transformer_script: ModuleType,
    tmp_path: Path,
) -> None:
    train_path, validation_path, tfidf_dir, output_dir = _prepare_coarse_inputs(
        transformer_script, tmp_path
    )
    arguments = transformer_script._build_parser().parse_args(
        [
            "--train-json",
            str(train_path),
            "--validation-json",
            str(validation_path),
            "--tfidf-output-dir",
            str(tfidf_dir),
            "--output-dir",
            str(output_dir),
            "--label-level",
            "coarse",
            "--max-length",
            "256",
            "--dry-run",
        ]
    )
    with pytest.raises(transformer_script.TransformerBaselineFailure, match="128"):
        transformer_script.run(arguments)


def test_annotation_manifest_requires_coarse_v2_label_level(
    transformer_script: ModuleType,
    tmp_path: Path,
) -> None:
    train_path, validation_path, tfidf_dir, output_dir = _prepare_coarse_inputs(
        transformer_script, tmp_path
    )
    manifest = tmp_path / "private-review.json"
    manifest.write_text("{}", encoding="utf-8")
    arguments = transformer_script._build_parser().parse_args(
        [
            "--train-json",
            str(train_path),
            "--validation-json",
            str(validation_path),
            "--tfidf-output-dir",
            str(tfidf_dir),
            "--output-dir",
            str(output_dir),
            "--label-level",
            "coarse",
            "--annotation-manifest",
            str(manifest),
            "--dry-run",
        ]
    )

    with pytest.raises(
        transformer_script.TransformerBaselineFailure,
        match="only be used with coarse-v2",
    ):
        transformer_script.run(arguments)


def test_coarse_v2_dry_run_reuses_exact_tfidf_split_and_order(
    transformer_script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (
        train_path,
        validation_path,
        annotation_path,
        tfidf_dir,
        output_dir,
    ) = _prepare_v2_inputs(transformer_script, tmp_path)
    tokenizer = TinyTokenizer()
    classifier_sizes: list[int] = []

    monkeypatch.setattr(transformer_script, "load_tokenizer", lambda name: tokenizer)

    def load_classifier(config: Any, labels: Any) -> TinyClassifier:
        del config
        classifier_sizes.append(len(labels.classes))
        return TinyClassifier(len(labels.classes))

    monkeypatch.setattr(transformer_script, "load_classifier", load_classifier)
    monkeypatch.setattr(
        transformer_script,
        "create_data_collator",
        lambda value: _collate,
    )
    code = transformer_script.main(
        [
            "--train-json",
            str(train_path),
            "--validation-json",
            str(validation_path),
            "--dataset-release-id",
            "synthetic-v2-release-001",
            "--tfidf-output-dir",
            str(tfidf_dir),
            "--output-dir",
            str(output_dir),
            "--label-level",
            "coarse-v2",
            "--model-name",
            "synthetic-model",
            "--device",
            "cpu",
            "--random-state",
            "7",
            "--dry-run",
            "--dry-run-samples",
            "12",
            "--disable-progress-bar",
        ]
    )
    captured = capsys.readouterr()
    dry_output = output_dir / "dry-run"

    assert code == 0
    assert classifier_sizes == [6]
    labels = json.loads((dry_output / "label_classes.json").read_text(encoding="utf-8"))
    run_config = json.loads(
        (dry_output / "run_config.json").read_text(encoding="utf-8")
    )
    split_summary = json.loads(
        (dry_output / "split_summary.json").read_text(encoding="utf-8")
    )
    assert labels["classes"] == list(EXPECTED_V2_LABELS)
    assert labels["label_field"] == "deterministic_remind_coarse_v2"
    assert "상처" not in labels["classes"]
    assert run_config["model_version"] == "klue-roberta-remind-coarse-v2"
    assert run_config["label_field"] == "deterministic_remind_coarse_v2"
    assert run_config["dataset_release_id"] == "synthetic-v2-release-001"
    assert run_config["annotation_revision"] is None
    assert run_config["training_random_state"] == 7
    assert run_config["split_random_state"] == 42
    assert run_config["class_weighting_resolved"] == "balanced"
    assert run_config["common_private_split_assignment_verified"] is True
    assert split_summary["exact_private_split_assignment_verified"] is True
    assert (dry_output / "preparation_report.json").is_file()
    assert (dry_output / "label_policy_summary.json").is_file()
    serialized = "".join(
        path.read_text(encoding="utf-8")
        for path in dry_output.iterdir()
        if path.is_file()
    )
    assert "PRIVATE-V2-TALK" not in serialized
    assert "PRIVATE-V2-PROFILE" not in serialized
    assert str(annotation_path) not in serialized
    assert str(train_path) not in serialized
    assert "PRIVATE" not in captured.out + captured.err


def test_coarse_v2_full_run_writes_apples_to_apples_comparison(
    transformer_script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        train_path,
        validation_path,
        _annotation_path,
        tfidf_dir,
        output_dir,
    ) = _prepare_v2_inputs(transformer_script, tmp_path)
    tokenizer = TinyTokenizer()
    monkeypatch.setattr(transformer_script, "load_tokenizer", lambda name: tokenizer)
    monkeypatch.setattr(
        transformer_script,
        "load_classifier",
        lambda config, labels: TinyClassifier(len(labels.classes)),
    )
    monkeypatch.setattr(
        transformer_script,
        "create_data_collator",
        lambda value: _collate,
    )
    code = transformer_script.main(
        [
            "--train-json",
            str(train_path),
            "--validation-json",
            str(validation_path),
            "--dataset-release-id",
            "synthetic-v2-release-001",
            "--tfidf-output-dir",
            str(tfidf_dir),
            "--output-dir",
            str(output_dir),
            "--label-level",
            "coarse-v2",
            "--model-name",
            "synthetic-model",
            "--device",
            "cpu",
            "--epochs",
            "1",
            "--train-batch-size",
            "6",
            "--eval-batch-size",
            "6",
            "--gradient-accumulation-steps",
            "1",
            "--benchmark-warmup-runs",
            "0",
            "--benchmark-runs",
            "1",
            "--disable-progress-bar",
        ]
    )

    assert code == 0
    comparison = json.loads(
        (output_dir / "comparison.json").read_text(encoding="utf-8")
    )
    metadata = json.loads(
        (output_dir / "model_metadata.json").read_text(encoding="utf-8")
    )
    run_config = json.loads(
        (output_dir / "run_config.json").read_text(encoding="utf-8")
    )
    trainer_state = json.loads(
        (output_dir / "checkpoints" / "last" / "trainer_state.json").read_text(
            encoding="utf-8"
        )
    )
    assert comparison["taxonomy_version"] == "remind-coarse-v2"
    assert comparison["ordered_labels"] == list(EXPECTED_V2_LABELS)
    assert comparison["common_private_split_verified"] is True
    assert comparison["models"]["tfidf"]["model_version"] == (
        "tfidf-logreg-remind-coarse-v2"
    )
    assert comparison["models"]["transformer"]["model_version"] == (
        "klue-roberta-remind-coarse-v2"
    )
    assert metadata["labels"] == list(EXPECTED_V2_LABELS)
    assert metadata["class_weighting"] == "balanced"
    assert metadata["run_fingerprint"] == run_config["run_fingerprint"]
    assert len(run_config["run_fingerprint"]) == 64
    provenance = trainer_state["checkpoint_provenance"]
    assert provenance["label_set_version"] == "remind-coarse-v2"
    assert provenance["ordered_labels"] == list(EXPECTED_V2_LABELS)
    assert provenance["dataset_release_id"] == "synthetic-v2-release-001"
    assert len(provenance["exact_split_sha256"]) == 64
    for name in (
        "classification_report.json",
        "confusion_matrix.json",
        "evaluation_summary.json",
        "inference_benchmark.json",
        "training_history.json",
        "test_metrics.json",
        "evaluation_state.json",
    ):
        assert (output_dir / name).is_file()
    assert (output_dir / "model").is_dir()
    assert (output_dir / "tokenizer").is_dir()


def test_relative_paths_and_split_mismatch_fail_without_path_disclosure(
    transformer_script: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = transformer_script.main(
        [
            "--train-json",
            "private.json",
            "--validation-json",
            "validation.json",
            "--tfidf-output-dir",
            "tfidf",
            "--output-dir",
            "output",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "private.json" not in captured.err

    train_path, validation_path, tfidf_dir, output_dir = _prepare_inputs(
        transformer_script, tmp_path
    )
    summary_path = tfidf_dir / "split_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["dataset"]["record_count"] += 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    code = transformer_script.main(
        [
            "--train-json",
            str(train_path),
            "--validation-json",
            str(validation_path),
            "--tfidf-output-dir",
            str(tfidf_dir),
            "--output-dir",
            str(output_dir),
            "--device",
            "cpu",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "does not match" in captured.err
    assert str(train_path) not in captured.err


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--learning-rate", "NaN"),
        ("--weight-decay", "Infinity"),
        ("--warmup-ratio", "NaN"),
        ("--max-grad-norm", "Infinity"),
    ],
)
def test_nonfinite_hyperparameters_are_rejected_by_the_parser(
    transformer_script: ModuleType, flag: str, value: str
) -> None:
    with pytest.raises(
        transformer_script.TransformerBaselineFailure,
        match="command arguments",
    ):
        transformer_script._build_parser().parse_args(
            [
                "--train-json",
                "train.json",
                "--validation-json",
                "validation.json",
                "--tfidf-output-dir",
                "tfidf",
                "--output-dir",
                "output",
                flag,
                value,
            ]
        )


def test_relative_local_model_name_is_rejected(
    transformer_script: ModuleType, tmp_path: Path
) -> None:
    train_path, validation_path, tfidf_dir, output_dir = _prepare_inputs(
        transformer_script, tmp_path
    )
    arguments = transformer_script._build_parser().parse_args(
        [
            "--train-json",
            str(train_path),
            "--validation-json",
            str(validation_path),
            "--tfidf-output-dir",
            str(tfidf_dir),
            "--output-dir",
            str(output_dir),
            "--model-name",
            "../PRIVATE/models/checkpoint",
            "--dry-run",
        ]
    )

    with pytest.raises(
        transformer_script.TransformerBaselineFailure,
        match="public model identifier",
    ):
        transformer_script.run(arguments)


def test_resume_provenance_mismatch_is_rejected_before_model_loading(
    transformer_script: ModuleType, tmp_path: Path
) -> None:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "trainer_state.json").write_text(
        json.dumps({"checkpoint_provenance": {"version": 1, "revision": 1}}),
        encoding="utf-8",
    )

    with pytest.raises(
        transformer_script.TransformerBaselineFailure,
        match="does not match",
    ):
        transformer_script._validate_resume_checkpoint_provenance(
            checkpoint, {"version": 1, "revision": 2}
        )


def test_completed_evaluation_is_blocked_unless_force_is_explicit(
    transformer_script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    train_path, validation_path, tfidf_dir, output_dir = _prepare_inputs(
        transformer_script, tmp_path
    )
    output_dir.mkdir()
    (output_dir / "evaluation_state.json").write_text(
        json.dumps({"final_evaluation_completed": True}), encoding="utf-8"
    )
    base_arguments = [
        "--train-json",
        str(train_path),
        "--validation-json",
        str(validation_path),
        "--tfidf-output-dir",
        str(tfidf_dir),
        "--output-dir",
        str(output_dir),
        "--device",
        "cpu",
    ]
    arguments = transformer_script._build_parser().parse_args(base_arguments)
    with pytest.raises(transformer_script.TransformerBaselineFailure, match="already"):
        transformer_script.run(arguments)

    class ForceReached(RuntimeError):
        pass

    monkeypatch.setattr(
        transformer_script,
        "load_json_samples",
        lambda *args, **kwargs: (_ for _ in ()).throw(ForceReached()),
    )
    forced = transformer_script._build_parser().parse_args(
        [*base_arguments, "--force-evaluate"]
    )
    with pytest.raises(ForceReached):
        transformer_script.run(forced)


def test_dry_run_rejects_resume_checkpoint_without_loading_or_serializing_it(
    transformer_script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_path, validation_path, tfidf_dir, output_dir = _prepare_inputs(
        transformer_script, tmp_path
    )
    checkpoint = tmp_path / "PRIVATE-CHECKPOINT-PATH"
    checkpoint.mkdir()
    loaded_sources: list[str] = []
    tokenizer = TinyTokenizer()

    def load_tokenizer(source: str) -> TinyTokenizer:
        loaded_sources.append(source)
        return tokenizer

    def load_classifier(config: Any, labels: Any) -> TinyClassifier:
        loaded_sources.append(config.model_name)
        return TinyClassifier(len(labels.classes))

    monkeypatch.setattr(transformer_script, "load_tokenizer", load_tokenizer)
    monkeypatch.setattr(transformer_script, "load_classifier", load_classifier)
    monkeypatch.setattr(
        transformer_script, "create_data_collator", lambda value: _collate
    )
    code = transformer_script.main(
        [
            "--train-json",
            str(train_path),
            "--validation-json",
            str(validation_path),
            "--tfidf-output-dir",
            str(tfidf_dir),
            "--output-dir",
            str(output_dir),
            "--model-name",
            "synthetic-model",
            "--device",
            "cpu",
            "--resume-from-checkpoint",
            str(checkpoint),
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert loaded_sources == []
    assert str(checkpoint) not in captured.err
    assert not output_dir.exists()
