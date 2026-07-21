"""Transformer-only views over approved emotion samples.

This module never serializes source text or identifiers.  IDs remain in the
shared ``EmotionSample`` objects only long enough to validate the group-safe
split and are not returned from dataset items.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .emotion_dataset import EmotionSample, TURN_SEPARATOR


class TransformerDatasetError(ValueError):
    """Raised with a value-safe message for invalid transformer input."""


@dataclass(frozen=True)
class LabelEncoding:
    """Stable sorted emotion.type label mapping."""

    classes: tuple[str, ...]
    label2id: Mapping[str, int]
    id2label: Mapping[int, str]


def build_label_encoding(samples: Sequence[EmotionSample]) -> LabelEncoding:
    """Build a deterministic mapping compatible with the TF-IDF class order."""

    classes = tuple(sorted({sample.label for sample in samples}))
    if len(classes) < 2:
        raise TransformerDatasetError("at least two emotion.type classes are required")
    label2id = {label: index for index, label in enumerate(classes)}
    return LabelEncoding(
        classes=classes,
        label2id=label2id,
        id2label={index: label for label, index in label2id.items()},
    )


def transformer_text(sample: EmotionSample, sep_token: str) -> str:
    """Replace the internal turn marker with the selected tokenizer separator."""

    if not isinstance(sep_token, str) or not sep_token.strip():
        raise TransformerDatasetError("the tokenizer separator token is unavailable")
    turns = [turn.strip() for turn in sample.text.split(TURN_SEPARATOR)]
    turns = [turn for turn in turns if turn]
    if not turns:
        raise TransformerDatasetError("approved user utterance text is empty")
    return f" {sep_token.strip()} ".join(turns)


class TokenizedEmotionDataset:
    """Lazy tokenizer adapter that exposes model features and label IDs only."""

    def __init__(
        self,
        samples: Sequence[EmotionSample],
        tokenizer: Any,
        labels: LabelEncoding,
        *,
        max_length: int = 128,
    ) -> None:
        if not samples:
            raise TransformerDatasetError("a transformer dataset split is empty")
        if max_length < 2:
            raise TransformerDatasetError("max_length must be at least two")
        sep_token = getattr(tokenizer, "sep_token", None)
        if not isinstance(sep_token, str) or not sep_token.strip():
            raise TransformerDatasetError("the tokenizer separator token is unavailable")
        unknown = {sample.label for sample in samples} - set(labels.classes)
        if unknown:
            raise TransformerDatasetError("a sample has an unknown emotion.type class")
        self._samples = tuple(samples)
        self._tokenizer = tokenizer
        self._labels = labels
        self._max_length = max_length
        self._sep_token = sep_token

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> dict[str, Any]:
        sample = self._samples[index]
        encoded = self._tokenizer(
            transformer_text(sample, self._sep_token),
            truncation=True,
            max_length=self._max_length,
            padding=False,
        )
        if not isinstance(encoded, Mapping):
            raise TransformerDatasetError("the tokenizer returned an unsupported batch")
        item = {name: value for name, value in encoded.items()}
        item["labels"] = self._labels.label2id[sample.label]
        return item


def safe_batch_shape(batch: Mapping[str, Any]) -> dict[str, object]:
    """Return aggregate batch dimensions without feature values."""

    result: dict[str, object] = {"fields": sorted(batch)}
    for name, value in batch.items():
        shape = getattr(value, "shape", None)
        if shape is not None:
            result[f"{name}_shape"] = [int(part) for part in shape]
    return result
