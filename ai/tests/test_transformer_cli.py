"""Synthetic, network-free tests for the Transformer baseline CLI."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
import sys

import pytest
from ai.src.remind_ai.data.emotion_dataset import load_json_samples
from ai.src.remind_ai.data.group_split import select_group_safe_split


torch = pytest.importorskip("torch")


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "ai" / "scripts" / "train_transformer_baseline.py"


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
    (tfidf_dir / "split_summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
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
    monkeypatch.setattr(transformer_script, "create_data_collator", lambda value: _collate)
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
    summary = json.loads((output_dir / "split_summary.json").read_text(encoding="utf-8"))
    assert summary["split_reused_from_tfidf"] is True
    for category in (
        "profile_id_overlap_count",
        "conversation_key_overlap_count",
        "normalized_text_overlap_count",
    ):
        assert all(value == 0 for value in summary["overlap_checks"][category].values())
    serialized = "".join(
        path.read_text(encoding="utf-8")
        for path in output_dir.iterdir()
        if path.is_file()
    ) + captured.out + captured.err
    assert "PRIVATE USER TEXT" not in serialized
    assert "PRIVATE-PROFILE" not in serialized
    assert "PRIVATE-RAW" not in serialized
    assert str(train_path) not in serialized
    assert not (output_dir / "test_metrics.json").exists()


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


def test_resume_checkpoint_is_used_but_never_serialized(
    transformer_script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.setattr(transformer_script, "create_data_collator", lambda value: _collate)
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
    assert code == 0
    assert loaded_sources == [str(checkpoint), str(checkpoint)]
    serialized = "".join(
        path.read_text(encoding="utf-8")
        for path in output_dir.iterdir()
        if path.is_file()
    )
    assert str(checkpoint) not in serialized
    assert "PRIVATE-CHECKPOINT-PATH" not in serialized
