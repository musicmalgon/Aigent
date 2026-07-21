"""Synthetic-only tests for Transformer feature construction."""

from __future__ import annotations

from typing import Any

import pytest

from ai.src.remind_ai.data.emotion_dataset import EmotionSample, sample_from_record
from ai.src.remind_ai.data.transformer_dataset import (
    TokenizedEmotionDataset,
    TransformerDatasetError,
    build_label_encoding,
    transformer_inference_text,
    transformer_text,
)


class RecordingTokenizer:
    sep_token = "[SEP]"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, text: str, **kwargs: Any) -> dict[str, list[int]]:
        self.calls.append((text, kwargs))
        size = min(len(text.split()), int(kwargs["max_length"]))
        return {"input_ids": list(range(size)), "attention_mask": [1] * size}


def _record(hs03: object = None, *, include_hs03: bool = True) -> dict[str, object]:
    content: dict[str, object] = {
        "HS01": "PRIVATE FIRST TURN",
        "HS02": "PRIVATE SECOND TURN",
        "SS01": "PRIVATE SYSTEM RESPONSE",
        "SS02": "PRIVATE SYSTEM RESPONSE",
        "SS03": "PRIVATE SYSTEM RESPONSE",
    }
    if include_hs03:
        content["HS03"] = hs03
    return {
        "profile": {"emotion": {"type": "SYNTH_B", "emotion-id": "IGNORED"}},
        "talk": {
            "content": content,
            "id": {"talk-id": "PRIVATE-TALK", "profile-id": "PRIVATE-PROFILE"},
        },
    }


@pytest.mark.parametrize(
    ("hs03", "include_hs03", "separator_count"),
    [("PRIVATE THIRD TURN", True, 2), (None, True, 1), (None, False, 1), ("  ", True, 1)],
)
def test_user_turns_use_tokenizer_separator_and_optional_hs03(
    hs03: object, include_hs03: bool, separator_count: int
) -> None:
    sample = sample_from_record(_record(hs03, include_hs03=include_hs03), "synthetic")
    text = transformer_text(sample, "[SEP]")
    assert text.count("[SEP]") == separator_count
    assert "SYSTEM RESPONSE" not in text
    assert "emotion-id" not in text


def test_label_mapping_is_sorted_and_tokenization_is_truncated_without_padding() -> None:
    samples = [
        EmotionSample("alpha [TURN] beta", "SYNTH_B", "ID-1", "GROUP-1", "synthetic"),
        EmotionSample("gamma [TURN] delta", "SYNTH_A", "ID-2", "GROUP-2", "synthetic"),
    ]
    labels = build_label_encoding(samples)
    tokenizer = RecordingTokenizer()
    dataset = TokenizedEmotionDataset(samples, tokenizer, labels, max_length=3)
    item = dataset[0]
    assert labels.classes == ("SYNTH_A", "SYNTH_B")
    assert labels.label2id == {"SYNTH_A": 0, "SYNTH_B": 1}
    assert item["labels"] == 1
    assert tokenizer.calls[0][1] == {
        "truncation": True,
        "max_length": 3,
        "padding": False,
    }


def test_explicit_label_order_is_preserved_and_requires_exact_coverage() -> None:
    samples = [
        EmotionSample("alpha", "A", "ID-1", "GROUP-1", "synthetic"),
        EmotionSample("beta", "B", "ID-2", "GROUP-2", "synthetic"),
    ]
    labels = build_label_encoding(samples, classes=("B", "A"))
    assert labels.classes == ("B", "A")
    assert labels.label2id == {"B": 0, "A": 1}
    with pytest.raises(TransformerDatasetError, match="do not match"):
        build_label_encoding(samples, classes=("A", "A"))
    with pytest.raises(TransformerDatasetError, match="do not match"):
        build_label_encoding(samples, classes=("A", "C"))


def test_empty_input_and_missing_separator_fail_safely() -> None:
    labels = build_label_encoding(
        [
            EmotionSample("a", "A", "ID-1", "G-1", "synthetic"),
            EmotionSample("b", "B", "ID-2", "G-2", "synthetic"),
        ]
    )
    blank = EmotionSample("  ", "A", "PRIVATE", "PRIVATE", "synthetic")
    with pytest.raises(TransformerDatasetError):
        transformer_text(blank, "[SEP]")
    tokenizer = RecordingTokenizer()
    tokenizer.sep_token = None  # type: ignore[assignment]
    with pytest.raises(TransformerDatasetError):
        TokenizedEmotionDataset([blank], tokenizer, labels)


def test_inference_turns_match_training_text_preprocessing() -> None:
    sample = sample_from_record(_record(" PRIVATE   THIRD TURN "), "synthetic")
    assert transformer_inference_text(
        " PRIVATE   FIRST TURN ",
        "PRIVATE SECOND TURN",
        " PRIVATE   THIRD TURN ",
        "[SEP]",
    ) == transformer_text(sample, "[SEP]")
