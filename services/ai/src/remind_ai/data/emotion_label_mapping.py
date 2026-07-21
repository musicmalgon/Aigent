"""Validated AI Hub fine-to-coarse emotion label mapping."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import json
from pathlib import Path

from ...schemas import COARSE_EMOTION_LABELS
from .emotion_dataset import EmotionSample


EXPECTED_FINE_LABELS = tuple(f"E{index}" for index in range(10, 70))
EXPECTED_COARSE_LABELS = tuple(label.value for label in COARSE_EMOTION_LABELS)


class EmotionLabelMappingError(ValueError):
    """Raised when the reviewable mapping artifact or its coverage is invalid."""


@dataclass(frozen=True)
class FineEmotionLabel:
    fine_name: str
    coarse_name: str


@dataclass(frozen=True)
class EmotionLabelMapping:
    version: int
    source: Mapping[str, object]
    coarse_labels: tuple[str, ...]
    official_coarse_labels: tuple[str, ...]
    fine_to_coarse: Mapping[str, FineEmotionLabel]


def _string_sequence(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise EmotionLabelMappingError(f"mapping {name} must be a non-empty string list")
    return tuple(item.strip() for item in value)


def load_emotion_label_mapping(path: Path) -> EmotionLabelMapping:
    """Load and fully validate the reviewable mapping artifact."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EmotionLabelMappingError("mapping file is invalid") from exc
    if not isinstance(payload, Mapping):
        raise EmotionLabelMappingError("mapping file must contain an object")
    version = payload.get("version")
    source = payload.get("source")
    if version != 1 or not isinstance(source, Mapping):
        raise EmotionLabelMappingError("mapping version or source is invalid")
    coarse_labels = _string_sequence(payload.get("coarse_labels"), "coarse_labels")
    official_labels = _string_sequence(
        payload.get("official_coarse_labels"), "official_coarse_labels"
    )
    if (
        len(coarse_labels) != 6
        or len(set(coarse_labels)) != 6
        or coarse_labels != EXPECTED_COARSE_LABELS
        or set(official_labels) != set(EXPECTED_COARSE_LABELS)
    ):
        raise EmotionLabelMappingError("mapping must define the six approved coarse labels")
    raw_mapping = payload.get("fine_to_coarse")
    if not isinstance(raw_mapping, Mapping):
        raise EmotionLabelMappingError("mapping fine_to_coarse is invalid")
    if set(raw_mapping) != set(EXPECTED_FINE_LABELS):
        missing = sorted(set(EXPECTED_FINE_LABELS) - set(raw_mapping))
        extra = sorted(set(raw_mapping) - set(EXPECTED_FINE_LABELS))
        raise EmotionLabelMappingError(
            f"mapping fine label coverage is invalid: missing={missing}, extra={extra}"
        )
    parsed: dict[str, FineEmotionLabel] = {}
    coarse_counts: Counter[str] = Counter()
    for fine_label in EXPECTED_FINE_LABELS:
        value = raw_mapping[fine_label]
        if not isinstance(value, Mapping):
            raise EmotionLabelMappingError(f"mapping entry for {fine_label} is invalid")
        fine_name = value.get("fine_name")
        coarse_name = value.get("coarse_name")
        if not isinstance(fine_name, str) or not fine_name.strip():
            raise EmotionLabelMappingError(
                f"mapping fine_name for {fine_label} is invalid"
            )
        if not isinstance(coarse_name, str) or coarse_name not in EXPECTED_COARSE_LABELS:
            raise EmotionLabelMappingError(
                f"mapping coarse_name for {fine_label} is invalid"
            )
        parsed[fine_label] = FineEmotionLabel(fine_name.strip(), coarse_name)
        coarse_counts[coarse_name] += 1
    if set(coarse_counts.values()) != {10}:
        raise EmotionLabelMappingError(
            "mapping must assign exactly ten fine labels to each coarse label"
        )
    return EmotionLabelMapping(
        version=version,
        source=dict(source),
        coarse_labels=coarse_labels,
        official_coarse_labels=official_labels,
        fine_to_coarse=parsed,
    )


def map_samples_to_coarse(
    samples: Sequence[EmotionSample],
    mapping: EmotionLabelMapping,
    *,
    mapping_path: Path,
) -> list[EmotionSample]:
    """Map every sample or fail with explicit coverage diagnostics."""

    del mapping_path
    unknown: dict[str, list[EmotionSample]] = defaultdict(list)
    for sample in samples:
        if sample.label not in mapping.fine_to_coarse:
            unknown[sample.label].append(sample)
    if unknown:
        fine_label = sorted(unknown)[0]
        affected = unknown[fine_label]
        raise EmotionLabelMappingError(
            "unknown fine label "
            f"{fine_label!r}; sample count={len(affected)}; "
            "mapping function="
            "ai.src.remind_ai.data.emotion_label_mapping.map_samples_to_coarse"
        )
    mapped = [
        replace(sample, label=mapping.fine_to_coarse[sample.label].coarse_name)
        for sample in samples
    ]
    if len(mapped) != len(samples):
        raise EmotionLabelMappingError("coarse mapping changed the sample count")
    return mapped


def mapping_validation_report(
    mapping: EmotionLabelMapping,
    original_samples: Sequence[EmotionSample],
    split_samples: Mapping[str, Sequence[EmotionSample]],
) -> dict[str, object]:
    """Build an aggregate-only coverage and distribution report."""

    mapped_count = sum(len(samples) for samples in split_samples.values())
    return {
        "mapping_version": mapping.version,
        "mapping_source": dict(mapping.source),
        "fine_label_count": len(mapping.fine_to_coarse),
        "coarse_label_count": len(mapping.coarse_labels),
        "coarse_labels": list(mapping.coarse_labels),
        "official_coarse_labels": list(mapping.official_coarse_labels),
        "coarse_to_fine": {
            coarse: [
                fine
                for fine, value in mapping.fine_to_coarse.items()
                if value.coarse_name == coarse
            ]
            for coarse in mapping.coarse_labels
        },
        "split_class_distribution": {
            name: dict(sorted(Counter(sample.label for sample in samples).items()))
            for name, samples in split_samples.items()
        },
        "unknown_label_count": 0,
        "unmapped_sample_count": 0,
        "original_sample_count": len(original_samples),
        "mapped_sample_count": mapped_count,
        "sample_count_preserved": mapped_count == len(original_samples),
    }
