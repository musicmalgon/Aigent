"""Focused tests for progress reporting and epoch history fields."""

from __future__ import annotations

from io import StringIO

from ai.src.remind_ai.training.progress import (
    ProgressConfig,
    ProgressReporter,
    epoch_summary,
    format_duration,
)


class _FakeBar:
    total = 2

    def __init__(self) -> None:
        self.postfixes: list[dict[str, object]] = []

    def set_postfix(self, values: dict[str, object], refresh: bool) -> None:
        assert refresh is False
        self.postfixes.append(values)


def test_progress_postfix_interval_and_disable_behavior() -> None:
    bar = _FakeBar()
    reporter = ProgressReporter(ProgressConfig(enabled=True, update_interval=2))
    reporter.update_postfix(bar, 1, {"loss": "1.0"})
    reporter.update_postfix(bar, 2, {"loss": "0.5", "step": 1, "accum": "2/2"})
    assert bar.postfixes == [{"loss": "0.5", "step": 1, "accum": "2/2"}]

    disabled = ProgressReporter(ProgressConfig(enabled=False))
    stream = StringIO()
    list(disabled.batches(range(2), total=2, desc="Non-TTY"))
    assert stream.getvalue() == ""


def test_duration_and_epoch_summary_include_operational_fields() -> None:
    assert format_duration(443.6) == "7m 24s"
    summary = epoch_summary(
        epoch=1,
        total_epochs=3,
        train_loss=1.8,
        validation={
            "loss": 1.5,
            "accuracy": 0.7,
            "macro_precision": 0.69,
            "macro_recall": 0.68,
            "macro_f1": 0.685,
            "weighted_f1": 0.7,
        },
        learning_rate=1.3e-5,
        train_duration="6m 52s",
        validation_duration="31s",
        epoch_duration="7m 23s",
        best_macro_f1=0.685,
        best_epoch=1,
        checkpoint_updated=True,
        early_stopping_count=0,
        early_stopping_patience=2,
    )
    for text in (
        "Epoch 1/3 Summary",
        "Train loss",
        "Validation loss",
        "Macro F1",
        "Best checkpoint  : updated",
        "Early stopping   : 0/2",
    ):
        assert text in summary
