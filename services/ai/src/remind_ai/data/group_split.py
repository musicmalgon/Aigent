"""Reproducible profile-isolated split selection with safe diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import importlib
import math
import re

from .emotion_dataset import EmotionSample, normalize_text


class GroupSplitError(ValueError):
    """A safe split failure with aggregate-only diagnostics."""

    def __init__(self, message: str, diagnostics: Mapping[str, object] | None = None):
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


@dataclass(frozen=True)
class GroupSplitResult:
    """Selected indices and aggregate candidate-quality information."""

    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    candidate_seed: int
    balance_score: float
    missing_validation_classes: tuple[str, ...]
    missing_test_classes: tuple[str, ...]
    evaluated_candidate_count: int
    fallback_used: bool

    def samples_for(
        self, samples: Sequence[EmotionSample], name: str
    ) -> list[EmotionSample]:
        indices = {
            "train": self.train_indices,
            "validation": self.validation_indices,
            "test": self.test_indices,
        }.get(name)
        if indices is None:
            raise GroupSplitError("an unknown internal split was requested")
        return [samples[index] for index in indices]


def _conversation_keys(samples: Sequence[EmotionSample]) -> set[tuple[str, str]]:
    return {(sample.group_id, sample.sample_id) for sample in samples}


def _overlap_count(
    left: Sequence[EmotionSample], right: Sequence[EmotionSample], attribute: str
) -> int:
    return len(
        {getattr(sample, attribute) for sample in left}
        & {getattr(sample, attribute) for sample in right}
    )


def _conversation_key_overlap_count(
    left: Sequence[EmotionSample], right: Sequence[EmotionSample]
) -> int:
    return len(_conversation_keys(left) & _conversation_keys(right))


def _quantiles(values: Sequence[int]) -> dict[str, int | float | None]:
    if not values:
        return {"min": None, "max": None, "mean": None, "p50": None, "p95": None}
    ordered = sorted(values)

    def at(fraction: float) -> int:
        return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]

    return {
        "min": min(ordered),
        "max": max(ordered),
        "mean": round(sum(ordered) / len(ordered), 3),
        "p50": at(0.50),
        "p95": at(0.95),
    }


def dataset_structure_statistics(samples: Sequence[EmotionSample]) -> dict[str, object]:
    """Return safe aggregate facts used in summaries and failure diagnostics."""

    record_counts = Counter(sample.label for sample in samples)
    profiles_by_label: dict[str, set[str]] = {}
    labels_by_profile: dict[str, set[str]] = {}
    records_by_profile: Counter[str] = Counter()
    conversation_counts: Counter[tuple[str, str]] = Counter()
    for sample in samples:
        profiles_by_label.setdefault(sample.label, set()).add(sample.group_id)
        labels_by_profile.setdefault(sample.group_id, set()).add(sample.label)
        records_by_profile[sample.group_id] += 1
        conversation_counts[(sample.group_id, sample.sample_id)] += 1
    return {
        "record_count": len(samples),
        "profile_count": len(records_by_profile),
        "class_count": len(record_counts),
        "class_record_counts": dict(sorted(record_counts.items())),
        "class_profile_counts": {
            label: len(profiles)
            for label, profiles in sorted(profiles_by_label.items())
        },
        "labels_per_profile": _quantiles(
            [len(labels) for labels in labels_by_profile.values()]
        ),
        "records_per_profile": _quantiles(list(records_by_profile.values())),
        "duplicate_conversation_key_count": sum(
            max(0, count - 1) for count in conversation_counts.values()
        ),
    }


def _group_shuffle_split(
    indices: Sequence[int],
    groups: Sequence[str],
    test_size: float,
    random_state: int,
) -> tuple[list[int], list[int]]:
    try:
        splitter_class = importlib.import_module(
            "sklearn.model_selection"
        ).GroupShuffleSplit
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise GroupSplitError(
            "scikit-learn is required for group-safe splitting"
        ) from exc
    splitter = splitter_class(
        n_splits=1, test_size=test_size, random_state=random_state
    )
    left, right = next(splitter.split(indices, groups=groups))
    return [indices[position] for position in left], [
        indices[position] for position in right
    ]


def _candidate_score(
    samples: Sequence[EmotionSample], partitions: Sequence[Sequence[int]]
) -> float:
    overall = Counter(sample.label for sample in samples)
    labels = set(overall)
    total = len(samples)
    score = 0.0
    for indices, target_ratio in zip(partitions, (0.8, 0.1, 0.1), strict=True):
        size = len(indices)
        score += abs(size / total - target_ratio)
        counts = Counter(samples[index].label for index in indices)
        score += sum(
            abs(counts[label] / size - overall[label] / total) for label in labels
        )
        if target_ratio < 0.8:
            score += len(labels - set(counts)) * 0.05
    return round(score, 12)


def _partition_failure_reason(
    samples: Sequence[EmotionSample], partitions: Sequence[Sequence[int]]
) -> str | None:
    if not all(partitions):
        return "empty_split"
    named = [[samples[index] for index in indices] for indices in partitions]
    for left_index in range(len(named)):
        for right_index in range(left_index + 1, len(named)):
            if _overlap_count(named[left_index], named[right_index], "group_id"):
                return "profile_overlap"
            if _conversation_key_overlap_count(named[left_index], named[right_index]):
                return "conversation_overlap"
    all_labels = {sample.label for sample in samples}
    if {sample.label for sample in named[0]} != all_labels:
        return "train_missing_classes"
    return None


def _candidate_partitions(
    samples: Sequence[EmotionSample], seed: int
) -> tuple[list[int], list[int], list[int]]:
    all_indices = list(range(len(samples)))
    profile_count = len({sample.group_id for sample in samples})
    # Temporary must retain at least two profile groups so it can become validation and test.
    temporary_ratio = max(0.2, 2 / profile_count)
    train_indices, temporary_indices = _group_shuffle_split(
        all_indices,
        [sample.group_id for sample in samples],
        temporary_ratio,
        seed,
    )
    validation_indices, test_indices = _group_shuffle_split(
        temporary_indices,
        [samples[index].group_id for index in temporary_indices],
        0.5,
        seed + 10_000,
    )
    return train_indices, validation_indices, test_indices


def _search_candidates(
    samples: Sequence[EmotionSample],
    *,
    base_random_state: int,
    start_offset: int,
    end_offset: int,
    failures: Counter[str],
) -> GroupSplitResult | None:
    best: GroupSplitResult | None = None
    all_labels = {sample.label for sample in samples}
    for offset in range(start_offset, end_offset):
        seed = base_random_state + offset
        try:
            partitions = _candidate_partitions(samples, seed)
        except (GroupSplitError, ValueError):
            failures["other"] += 1
            continue
        failure_reason = _partition_failure_reason(samples, partitions)
        if failure_reason is not None:
            failures[failure_reason] += 1
            continue
        train_indices, validation_indices, test_indices = partitions
        candidate = GroupSplitResult(
            train_indices=tuple(sorted(train_indices)),
            validation_indices=tuple(sorted(validation_indices)),
            test_indices=tuple(sorted(test_indices)),
            candidate_seed=seed,
            balance_score=_candidate_score(samples, partitions),
            missing_validation_classes=tuple(
                sorted(
                    all_labels - {samples[index].label for index in validation_indices}
                )
            ),
            missing_test_classes=tuple(
                sorted(all_labels - {samples[index].label for index in test_indices})
            ),
            evaluated_candidate_count=end_offset,
            fallback_used=end_offset > 200,
        )
        if best is None or (candidate.balance_score, candidate.candidate_seed) < (
            best.balance_score,
            best.candidate_seed,
        ):
            best = candidate
    return best


def select_group_safe_split(
    samples: Sequence[EmotionSample],
    *,
    random_state: int = 42,
    candidate_count: int = 200,
) -> GroupSplitResult:
    """Choose the lowest-score candidate that satisfies only hard constraints."""

    diagnostics: dict[str, object] = {
        "dataset": dataset_structure_statistics(samples),
        "requested_candidate_count": candidate_count,
        "failure_counts": {
            "empty_split": 0,
            "profile_overlap": 0,
            "conversation_overlap": 0,
            "train_missing_classes": 0,
            "other": 0,
        },
    }
    if candidate_count < 1:
        raise GroupSplitError("candidate_count must be at least one", diagnostics)
    if len(samples) < 3:
        raise GroupSplitError(
            "at least three records are required for three splits", diagnostics
        )
    if len({sample.label for sample in samples}) < 2:
        raise GroupSplitError(
            "at least two classes are required for model training", diagnostics
        )
    if len({sample.group_id for sample in samples}) < 3:
        raise GroupSplitError("at least three profile groups are required", diagnostics)

    failures = Counter[str]()
    initial_limit = min(max(candidate_count, 200), 1_000)
    result = _search_candidates(
        samples,
        base_random_state=random_state,
        start_offset=0,
        end_offset=initial_limit,
        failures=failures,
    )
    fallback_used = result is None and initial_limit < 1_000
    if fallback_used:
        result = _search_candidates(
            samples,
            base_random_state=random_state,
            start_offset=initial_limit,
            end_offset=1_000,
            failures=failures,
        )
    evaluated_candidate_count = min(
        1_000 if fallback_used else initial_limit,
        1_000,
    )
    diagnostics["evaluated_candidate_count"] = evaluated_candidate_count
    diagnostics["fallback_used"] = fallback_used
    diagnostics["failure_counts"] = {
        name: failures.get(name, 0)
        for name in (
            "empty_split",
            "profile_overlap",
            "conversation_overlap",
            "train_missing_classes",
            "other",
        )
    }
    if result is None:
        raise GroupSplitError(
            "no profile-isolated split candidate could be selected", diagnostics
        )
    return replace(
        result,
        evaluated_candidate_count=evaluated_candidate_count,
        fallback_used=fallback_used,
    )


def _normalized_for_overlap(value: str) -> str:
    return re.sub(r"[A-Z]", lambda match: match.group(0).lower(), normalize_text(value))


def split_leakage_statistics(
    split_samples: Mapping[str, Sequence[EmotionSample]],
) -> dict[str, object]:
    """Return aggregate overlap counts; raw talk-id is explicitly non-blocking."""

    names = ("train", "validation", "test")
    result: dict[str, dict[str, int]] = {
        "profile_id_overlap_count": {},
        "conversation_key_overlap_count": {},
        "raw_talk_id_overlap_count": {},
        "normalized_text_overlap_count": {},
    }
    for left_index, left_name in enumerate(names):
        for right_name in names[left_index + 1 :]:
            key = f"{left_name}_vs_{right_name}"
            left = split_samples[left_name]
            right = split_samples[right_name]
            result["profile_id_overlap_count"][key] = _overlap_count(
                left, right, "group_id"
            )
            result["conversation_key_overlap_count"][key] = (
                _conversation_key_overlap_count(left, right)
            )
            result["raw_talk_id_overlap_count"][key] = _overlap_count(
                left, right, "sample_id"
            )
            result["normalized_text_overlap_count"][key] = len(
                {_normalized_for_overlap(sample.text) for sample in left}
                & {_normalized_for_overlap(sample.text) for sample in right}
            )
    return {**result, "raw_talk_id_overlap_is_blocking": False}
