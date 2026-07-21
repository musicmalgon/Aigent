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
        loss = torch.nn.functional.cross_entropy(logits, labels)
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
        config=TrainingConfig(epochs=1, gradient_accumulation_steps=2),
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
        config=TrainingConfig(epochs=2, gradient_accumulation_steps=2),
        resume_from_checkpoint=last,
    )
    assert resumed.best_epoch == 2
    assert resumed.optimizer_step_count == 2
    assert len(resumed.history) == 2


def test_interrupted_checkpoint_save_preserves_existing_checkpoint(tmp_path: Path) -> None:
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
