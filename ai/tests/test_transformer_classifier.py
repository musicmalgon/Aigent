"""Tests for device handling, stable metrics, and TF-IDF comparison."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.src.remind_ai.data.emotion_dataset import EmotionSample
from ai.src.remind_ai.data.transformer_dataset import build_label_encoding
from ai.src.remind_ai.models.transformer_classifier import (
    TransformerModelError,
    classification_metrics,
    comparison_payload,
    select_device,
)


class Availability:
    def __init__(self, available: bool) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available


def _torch(cuda: bool, mps: bool) -> SimpleNamespace:
    return SimpleNamespace(
        cuda=Availability(cuda), backends=SimpleNamespace(mps=Availability(mps))
    )


@pytest.mark.parametrize(
    ("cuda", "mps", "expected"),
    [(True, True, "cuda"), (False, True, "mps"), (False, False, "cpu")],
)
def test_auto_device_priority(cuda: bool, mps: bool, expected: str) -> None:
    assert select_device("auto", torch_module=_torch(cuda, mps)).selected == expected


def test_explicit_device_error_and_cpu_fallback() -> None:
    unavailable = _torch(False, False)
    with pytest.raises(TransformerModelError):
        select_device("cuda", torch_module=unavailable)
    with pytest.raises(TransformerModelError):
        select_device("cpu", fp16_requested=True, torch_module=unavailable)
    selection = select_device(
        "mps", allow_cpu_fallback=True, torch_module=unavailable
    )
    assert selection.selected == "cpu"
    assert selection.cpu_fallback_used is True
    assert select_device("cpu", torch_module=unavailable).selected == "cpu"


def test_metrics_include_macro_weighted_confusion_and_distributions() -> None:
    labels = build_label_encoding(
        [
            EmotionSample("a", "A", "1", "1", "synthetic"),
            EmotionSample("b", "B", "2", "2", "synthetic"),
        ]
    )
    metrics = classification_metrics([0, 0, 1], [0, 1, 1], labels)
    assert metrics["macro_f1"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["weighted_f1"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["confusion_matrix"] == {
        "labels": ["A", "B"],
        "matrix": [[1, 1], [0, 1]],
    }
    assert metrics["predicted_class_distribution"] == {"A": 1, "B": 2}


def test_comparison_uses_internal_test_and_handles_zero_division() -> None:
    payload = comparison_payload(
        {"accuracy": 0.5, "macro_f1": 0.4, "weighted_f1": 0.45},
        {"accuracy": 0.3, "macro_f1": 0.2, "weighted_f1": 0.25},
        model_name="synthetic-model",
        selected_tfidf_model="char_tfidf",
    )
    assert payload["absolute_macro_f1_improvement"] == 0.2
    assert payload["relative_macro_f1_improvement"] == 1.0
    zero = comparison_payload(
        None,
        {"accuracy": 0.0, "macro_f1": 0.0, "weighted_f1": 0.0},
        model_name="synthetic-model",
        selected_tfidf_model="char_tfidf",
    )
    assert zero["relative_macro_f1_improvement"] is None
