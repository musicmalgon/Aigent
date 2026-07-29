"""Offline tests for trainer policy and evaluation state."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from ai.src.remind_ai.data.emotion_dataset import EmotionSample
from ai.src.remind_ai.data.transformer_dataset import build_label_encoding
from ai.src.remind_ai.training import transformer_trainer
from ai.src.remind_ai.training.transformer_trainer import (
    TrainingConfig,
    benchmark_inference,
    evaluation_already_completed,
    fit,
)

torch = pytest.importorskip("torch")


class TinyClassifier(torch.nn.Module):  # type: ignore[name-defined]
    def __init__(self) -> None:
        super().__init__()
        self.linear = torch.nn.Linear(2, 2)

    def forward(self, input_ids: Any, labels: Any | None = None) -> Any:
        logits = self.linear(input_ids.float())
        loss = (
            torch.nn.functional.cross_entropy(logits, labels)
            if labels is not None
            else None
        )
        return SimpleNamespace(logits=logits, loss=loss)

    def save_pretrained(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        torch.save(self.state_dict(), directory / "pytorch_model.bin")


class TinyTokenizer:
    def save_pretrained(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tokenizer_config.json").write_text("{}", encoding="utf-8")


def _loader() -> list[dict[str, Any]]:
    return [
        {
            "input_ids": torch.tensor([[1.0, 0.0], [0.0, 1.0]]),
            "labels": torch.tensor([0, 1]),
        },
        {
            "input_ids": torch.tensor([[0.8, 0.2], [0.2, 0.8]]),
            "labels": torch.tensor([0, 1]),
        },
    ]


def test_fit_selects_best_stops_early_and_accumulates_gradients(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scores = iter([0.8, 0.7, 0.6])

    def fake_evaluate(*args: Any, **kwargs: Any) -> dict[str, object]:
        del args, kwargs
        return {"macro_f1": next(scores)}

    monkeypatch.setattr(transformer_trainer, "evaluate", fake_evaluate)
    labels = build_label_encoding(
        [
            EmotionSample("a", "A", "1", "1", "synthetic"),
            EmotionSample("b", "B", "2", "2", "synthetic"),
        ]
    )
    result = fit(
        torch=torch,
        model=TinyClassifier(),
        tokenizer=TinyTokenizer(),
        train_loader=_loader(),
        validation_loader=_loader(),
        labels=labels,
        device=torch.device("cpu"),
        checkpoints_dir=tmp_path / "checkpoints",
        config=TrainingConfig(
            epochs=4,
            gradient_accumulation_steps=2,
            early_stopping_patience=2,
        ),
    )
    assert result.best_epoch == 1
    assert result.stopped_early is True
    assert result.optimizer_step_count == 3
    assert (tmp_path / "checkpoints" / "best").is_dir()
    first_epoch = result.history[0]
    for key in (
        "train_loss",
        "validation_loss",
        "learning_rate",
        "optimizer_step_count",
        "train_seconds",
        "validation_seconds",
        "epoch_seconds",
        "train_duration",
        "validation_duration",
        "epoch_duration",
        "estimated_remaining_seconds",
    ):
        assert key in first_epoch


def test_evaluation_state_requires_explicit_force_policy(tmp_path: Path) -> None:
    state = tmp_path / "evaluation_state.json"
    assert evaluation_already_completed(state) is False
    state.write_text(json.dumps({"final_evaluation_completed": True}), encoding="utf-8")
    assert evaluation_already_completed(state) is True


def test_native_checkpoint_restores_epoch_optimizer_and_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    labels = build_label_encoding(
        [
            EmotionSample("a", "A", "1", "1", "synthetic"),
            EmotionSample("b", "B", "2", "2", "synthetic"),
        ]
    )
    monkeypatch.setattr(
        transformer_trainer,
        "evaluate",
        lambda *args, **kwargs: {"macro_f1": 0.7},
    )
    checkpoints = tmp_path / "checkpoints"
    provenance = {"version": 1, "run": "native-resume-test"}
    first_model = TinyClassifier()
    first = fit(
        torch=torch,
        model=first_model,
        tokenizer=TinyTokenizer(),
        train_loader=_loader(),
        validation_loader=_loader(),
        labels=labels,
        device=torch.device("cpu"),
        checkpoints_dir=checkpoints,
        config=TrainingConfig(
            epochs=1,
            gradient_accumulation_steps=2,
            checkpoint_provenance=provenance,
        ),
    )
    assert first.optimizer_step_count == 1
    last = checkpoints / "last"
    resumed_model = TinyClassifier()
    resumed_model.load_state_dict(
        torch.load(last / "pytorch_model.bin", map_location="cpu", weights_only=True)
    )
    monkeypatch.setattr(
        transformer_trainer,
        "evaluate",
        lambda *args, **kwargs: {"macro_f1": 0.8},
    )
    resumed = fit(
        torch=torch,
        model=resumed_model,
        tokenizer=TinyTokenizer(),
        train_loader=_loader(),
        validation_loader=_loader(),
        labels=labels,
        device=torch.device("cpu"),
        checkpoints_dir=checkpoints,
        config=TrainingConfig(
            epochs=2,
            gradient_accumulation_steps=2,
            checkpoint_provenance=provenance,
        ),
        resume_from_checkpoint=last,
    )
    assert resumed.best_epoch == 2
    assert resumed.optimizer_step_count == 2
    assert len(resumed.history) == 2


def test_resume_without_improvement_reloads_the_previous_best_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    labels = build_label_encoding(
        [
            EmotionSample("a", "A", "1", "1", "synthetic"),
            EmotionSample("b", "B", "2", "2", "synthetic"),
        ]
    )
    scores = iter([0.8, 0.7])
    monkeypatch.setattr(
        transformer_trainer,
        "evaluate",
        lambda *args, **kwargs: {"macro_f1": next(scores)},
    )
    checkpoints = tmp_path / "checkpoints"
    provenance = {"version": 1, "run": "best-resume-test"}
    fit(
        torch=torch,
        model=TinyClassifier(),
        tokenizer=TinyTokenizer(),
        train_loader=_loader(),
        validation_loader=_loader(),
        labels=labels,
        device=torch.device("cpu"),
        checkpoints_dir=checkpoints,
        config=TrainingConfig(
            epochs=2,
            gradient_accumulation_steps=2,
            early_stopping_patience=3,
            checkpoint_provenance=provenance,
        ),
    )
    best_state = torch.load(
        checkpoints / "best" / "pytorch_model.bin",
        map_location="cpu",
        weights_only=True,
    )
    last_state = torch.load(
        checkpoints / "last" / "pytorch_model.bin",
        map_location="cpu",
        weights_only=True,
    )
    assert any(
        not torch.equal(best_state[name], last_state[name]) for name in best_state
    )
    resumed_model = TinyClassifier()
    resumed_model.load_state_dict(last_state)
    monkeypatch.setattr(
        transformer_trainer,
        "evaluate",
        lambda *args, **kwargs: {"macro_f1": 0.6},
    )

    result = fit(
        torch=torch,
        model=resumed_model,
        tokenizer=TinyTokenizer(),
        train_loader=_loader(),
        validation_loader=_loader(),
        labels=labels,
        device=torch.device("cpu"),
        checkpoints_dir=checkpoints,
        config=TrainingConfig(
            epochs=3,
            gradient_accumulation_steps=2,
            early_stopping_patience=3,
            checkpoint_provenance=provenance,
        ),
        resume_from_checkpoint=checkpoints / "last",
    )

    assert result.best_epoch == 1
    for name, expected in best_state.items():
        assert torch.equal(resumed_model.state_dict()[name], expected)


def test_resume_rejects_mismatched_checkpoint_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    labels = build_label_encoding(
        [
            EmotionSample("a", "A", "1", "1", "synthetic"),
            EmotionSample("b", "B", "2", "2", "synthetic"),
        ]
    )
    monkeypatch.setattr(
        transformer_trainer,
        "evaluate",
        lambda *args, **kwargs: {"macro_f1": 0.7},
    )
    checkpoints = tmp_path / "checkpoints"
    model = TinyClassifier()
    fit(
        torch=torch,
        model=model,
        tokenizer=TinyTokenizer(),
        train_loader=_loader(),
        validation_loader=_loader(),
        labels=labels,
        device=torch.device("cpu"),
        checkpoints_dir=checkpoints,
        config=TrainingConfig(
            epochs=1,
            checkpoint_provenance={"version": 1, "revision": 1},
        ),
    )
    resumed_model = TinyClassifier()
    resumed_model.load_state_dict(
        torch.load(
            checkpoints / "last" / "pytorch_model.bin",
            map_location="cpu",
            weights_only=True,
        )
    )

    with pytest.raises(
        transformer_trainer.TransformerTrainingError,
        match="valid trainer state",
    ):
        fit(
            torch=torch,
            model=resumed_model,
            tokenizer=TinyTokenizer(),
            train_loader=_loader(),
            validation_loader=_loader(),
            labels=labels,
            device=torch.device("cpu"),
            checkpoints_dir=checkpoints,
            config=TrainingConfig(
                epochs=2,
                checkpoint_provenance={"version": 1, "revision": 2},
            ),
            resume_from_checkpoint=checkpoints / "last",
        )


def test_interrupted_checkpoint_save_preserves_existing_checkpoint(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoints" / "best"
    checkpoint.mkdir(parents=True)
    marker = checkpoint / "existing.bin"
    marker.write_text("preserve", encoding="utf-8")

    class InterruptedModel:
        def save_pretrained(self, directory: Path, **kwargs: Any) -> None:
            del directory, kwargs
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        transformer_trainer._save_checkpoint(
            InterruptedModel(), TinyTokenizer(), checkpoint, torch=torch
        )
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_weighted_training_uses_explicit_label_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    labels = build_label_encoding(
        [
            EmotionSample("a", "A", "1", "1", "synthetic"),
            EmotionSample("b", "B", "2", "2", "synthetic"),
        ],
        classes=("B", "A"),
    )
    captured_weights: list[list[float]] = []
    original_cross_entropy = torch.nn.functional.cross_entropy

    def capture_cross_entropy(*args: Any, **kwargs: Any) -> Any:
        weight = kwargs.get("weight")
        if weight is not None:
            captured_weights.append(weight.detach().cpu().tolist())
        return original_cross_entropy(*args, **kwargs)

    monkeypatch.setattr(torch.nn.functional, "cross_entropy", capture_cross_entropy)
    monkeypatch.setattr(
        transformer_trainer,
        "evaluate",
        lambda *args, **kwargs: {"macro_f1": 0.5},
    )
    fit(
        torch=torch,
        model=TinyClassifier(),
        tokenizer=TinyTokenizer(),
        train_loader=_loader(),
        validation_loader=_loader(),
        labels=labels,
        device=torch.device("cpu"),
        checkpoints_dir=tmp_path / "weighted",
        config=TrainingConfig(
            epochs=1,
            gradient_accumulation_steps=2,
            class_weights=(2.0, 0.5),
        ),
    )
    assert captured_weights
    assert captured_weights[0] == [2.0, 0.5]


def test_invalid_class_weights_fail_before_training(tmp_path: Path) -> None:
    labels = build_label_encoding(
        [
            EmotionSample("a", "A", "1", "1", "synthetic"),
            EmotionSample("b", "B", "2", "2", "synthetic"),
        ]
    )
    with pytest.raises(
        transformer_trainer.TransformerTrainingError,
        match="class weights",
    ):
        fit(
            torch=torch,
            model=TinyClassifier(),
            tokenizer=TinyTokenizer(),
            train_loader=_loader(),
            validation_loader=_loader(),
            labels=labels,
            device=torch.device("cpu"),
            checkpoints_dir=tmp_path / "invalid",
            config=TrainingConfig(class_weights=(1.0,)),
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("learning_rate", float("nan")),
        ("weight_decay", float("inf")),
        ("warmup_ratio", float("nan")),
        ("max_grad_norm", float("inf")),
    ],
)
def test_nonfinite_training_hyperparameters_fail_before_training(
    tmp_path: Path, name: str, value: float
) -> None:
    labels = build_label_encoding(
        [
            EmotionSample("a", "A", "1", "1", "synthetic"),
            EmotionSample("b", "B", "2", "2", "synthetic"),
        ]
    )

    with pytest.raises(
        transformer_trainer.TransformerTrainingError,
        match="finite",
    ):
        fit(
            torch=torch,
            model=TinyClassifier(),
            tokenizer=TinyTokenizer(),
            train_loader=_loader(),
            validation_loader=_loader(),
            labels=labels,
            device=torch.device("cpu"),
            checkpoints_dir=tmp_path / "nonfinite",
            config=TrainingConfig(**{name: value}),
        )


def test_inference_benchmark_excludes_labels_and_reports_latency() -> None:
    model = TinyClassifier()
    observed_label_presence: list[bool] = []

    def batch_factory() -> dict[str, Any]:
        batch = {
            "input_ids": torch.tensor([[1.0, 0.0], [0.0, 1.0]]),
            "labels": torch.tensor([0, 1]),
        }
        observed_label_presence.append("labels" in batch)
        return batch

    result = benchmark_inference(
        torch=torch,
        model=model,
        batch_factory=batch_factory,
        device=torch.device("cpu"),
        effective_batch_size=2,
        warmup_runs=1,
        measured_runs=2,
    )
    assert observed_label_presence == [True, True, True]
    assert result["effective_batch_size"] == 2
    assert result["p50_latency_ms"] >= 0
    assert result["p95_latency_ms"] >= 0
    assert result["samples_per_second"] > 0
