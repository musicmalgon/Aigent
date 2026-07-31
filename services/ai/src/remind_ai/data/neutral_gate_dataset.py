"""Strict local dataset contract for the neutral/emotional binary gate."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .emotion_dataset import TURN_SEPARATOR, EmotionSample, normalize_text

NEUTRAL_LABEL = "neutral"
EMOTIONAL_LABEL = "emotional"
NEUTRAL_GATE_LABELS = (NEUTRAL_LABEL, EMOTIONAL_LABEL)
NEUTRAL_GATE_SPLITS = ("train", "validation", "calibration", "test")


class NeutralGateDatasetError(ValueError):
    """Value-safe failure that never includes source text or identifiers."""


@dataclass(frozen=True, slots=True)
class NeutralGateDataset:
    samples_by_split: Mapping[str, tuple[EmotionSample, ...]]
    summary: Mapping[str, object]


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NeutralGateDatasetError(f"{name} must be a non-empty string")
    return value.strip()


def _parse_record(payload: Mapping[str, object]) -> EmotionSample:
    if set(payload) != {"id", "group_id", "split", "label", "turns"}:
        raise NeutralGateDatasetError("a neutral gate record has invalid fields")
    sample_id = _required_string(payload.get("id"), "id")
    group_id = _required_string(payload.get("group_id"), "group_id")
    split = _required_string(payload.get("split"), "split")
    label = _required_string(payload.get("label"), "label")
    turns = payload.get("turns")
    if split not in NEUTRAL_GATE_SPLITS:
        raise NeutralGateDatasetError("a neutral gate split is invalid")
    if label not in NEUTRAL_GATE_LABELS:
        raise NeutralGateDatasetError("a neutral gate label is invalid")
    if not isinstance(turns, list) or not 2 <= len(turns) <= 3:
        raise NeutralGateDatasetError("turns must contain two or three strings")
    normalized_turns = [
        normalize_text(_required_string(turn, "turn")) for turn in turns
    ]
    if len(set(normalized_turns)) != len(normalized_turns):
        raise NeutralGateDatasetError("turns within a record must be distinct")
    return EmotionSample(
        text=TURN_SEPARATOR.join(normalized_turns),
        label=label,
        sample_id=sample_id,
        group_id=group_id,
        official_split=split,
    )


def load_neutral_gate_dataset(path: Path) -> NeutralGateDataset:
    samples: list[EmotionSample] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line)
                if not isinstance(payload, Mapping):
                    raise NeutralGateDatasetError(
                        "a neutral gate JSONL row must be an object"
                    )
                samples.append(_parse_record(payload))
    except NeutralGateDatasetError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NeutralGateDatasetError("the neutral gate JSONL file is invalid") from exc
    if not samples:
        raise NeutralGateDatasetError("the neutral gate dataset is empty")
    if len({sample.sample_id for sample in samples}) != len(samples):
        raise NeutralGateDatasetError("neutral gate sample IDs must be unique")

    split_by_group: dict[str, str] = {}
    split_by_text: dict[str, str] = {}
    samples_by_split: dict[str, list[EmotionSample]] = {
        split: [] for split in NEUTRAL_GATE_SPLITS
    }
    for sample in samples:
        split = sample.official_split
        previous_group_split = split_by_group.setdefault(sample.group_id, split)
        if previous_group_split != split:
            raise NeutralGateDatasetError("a group appears in multiple splits")
        text_digest = hashlib.sha256(sample.text.encode("utf-8")).hexdigest()
        previous_text_split = split_by_text.setdefault(text_digest, split)
        if previous_text_split != split:
            raise NeutralGateDatasetError("duplicate text appears in multiple splits")
        samples_by_split[split].append(sample)

    distribution: dict[str, dict[str, int]] = {}
    for split, split_samples in samples_by_split.items():
        if not split_samples:
            raise NeutralGateDatasetError(f"{split} split is empty")
        counts = Counter(sample.label for sample in split_samples)
        if set(counts) != set(NEUTRAL_GATE_LABELS):
            raise NeutralGateDatasetError(
                f"{split} split must contain both gate labels"
            )
        distribution[split] = {label: counts[label] for label in NEUTRAL_GATE_LABELS}

    return NeutralGateDataset(
        samples_by_split={
            split: tuple(split_samples)
            for split, split_samples in samples_by_split.items()
        },
        summary={
            "sample_count": len(samples),
            "group_count": len(split_by_group),
            "text_duplicate_count_across_splits": 0,
            "group_overlap_count": 0,
            "distribution": distribution,
        },
    )


def balanced_emotional_samples(
    samples: Sequence[EmotionSample],
    *,
    per_class: int,
    random_state: int,
    split: str,
) -> tuple[EmotionSample, ...]:
    """Convert an existing six-class split into balanced emotional examples."""

    if per_class < 1:
        raise NeutralGateDatasetError("per_class must be positive")
    import random

    grouped: dict[str, list[EmotionSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.label, []).append(sample)
    if len(grouped) != 6 or any(len(rows) < per_class for rows in grouped.values()):
        raise NeutralGateDatasetError(
            "six emotion classes with enough samples are required"
        )
    rng = random.Random(random_state)
    selected: list[EmotionSample] = []
    for label in sorted(grouped):
        rows = list(grouped[label])
        rng.shuffle(rows)
        selected.extend(
            EmotionSample(
                text=row.text,
                label=EMOTIONAL_LABEL,
                sample_id=f"emotional:{row.sample_id}",
                group_id=f"emotional:{row.group_id}",
                official_split=split,
            )
            for row in rows[:per_class]
        )
    rng.shuffle(selected)
    return tuple(selected)


__all__ = [
    "EMOTIONAL_LABEL",
    "NEUTRAL_GATE_LABELS",
    "NEUTRAL_GATE_SPLITS",
    "NEUTRAL_LABEL",
    "NeutralGateDataset",
    "NeutralGateDatasetError",
    "balanced_emotional_samples",
    "load_neutral_gate_dataset",
]
