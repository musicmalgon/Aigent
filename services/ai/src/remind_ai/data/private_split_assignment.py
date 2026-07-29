"""Exact, local-only split assignment shared by TF-IDF and Transformer runs.

This file intentionally contains source identifiers and text digests.  It must
remain under a gitignored local output directory and must never be included in
shareable model artifacts or reports.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from .emotion_dataset import EmotionSample
from .group_split import GroupSplitResult

PRIVATE_SPLIT_ASSIGNMENT_VERSION = 2
PARTITION_NAMES = ("train", "validation", "test")


class PrivateSplitAssignmentError(ValueError):
    """Raised without echoing private values, digests, or filesystem paths."""


def _sample_key(sample: EmotionSample) -> tuple[str, str, str, str]:
    return (
        sample.official_split,
        sample.group_id,
        sample.sample_id,
        _text_digest(sample),
    )


def _text_digest(sample: EmotionSample) -> str:
    return hashlib.sha256(sample.text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".private-split-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
    except Exception as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise PrivateSplitAssignmentError(
            "the private split assignment could not be written safely"
        ) from exc


def write_private_split_assignment(
    path: Path,
    samples: Sequence[EmotionSample],
    split: GroupSplitResult,
    *,
    label_set_version: str,
    random_state: int,
    candidate_count: int,
) -> None:
    """Persist exact membership after validating one-to-one sample coverage."""

    if not path.is_absolute():
        raise PrivateSplitAssignmentError(
            "the private split assignment path must be absolute"
        )
    keys = [_sample_key(sample) for sample in samples]
    if len(set(keys)) != len(keys):
        raise PrivateSplitAssignmentError(
            "samples contain duplicate private split keys"
        )
    membership: dict[int, str] = {}
    for partition, indices in (
        ("train", split.train_indices),
        ("validation", split.validation_indices),
        ("test", split.test_indices),
    ):
        for index in indices:
            if index < 0 or index >= len(samples) or index in membership:
                raise PrivateSplitAssignmentError(
                    "the selected split membership is invalid"
                )
            membership[index] = partition
    if set(membership) != set(range(len(samples))):
        raise PrivateSplitAssignmentError(
            "the selected split does not cover every prepared sample"
        )
    records = [
        {
            "official_split": sample.official_split,
            "profile_id": sample.group_id,
            "talk_id": sample.sample_id,
            "label": sample.label,
            "text_sha256": _text_digest(sample),
            "partition": membership[index],
        }
        for index, sample in enumerate(samples)
    ]
    _write_json(
        path,
        {
            "version": PRIVATE_SPLIT_ASSIGNMENT_VERSION,
            "private": True,
            "contains_source_identifiers": True,
            "shareable": False,
            "label_set_version": label_set_version,
            "random_state": random_state,
            "candidate_count": candidate_count,
            "candidate_seed": split.candidate_seed,
            "balance_score": split.balance_score,
            "evaluated_candidate_count": split.evaluated_candidate_count,
            "fallback_used": split.fallback_used,
            "records": records,
        },
    )


def load_private_split_assignment(
    path: Path,
    samples: Sequence[EmotionSample],
    *,
    expected_label_set_version: str,
    expected_random_state: int | None = None,
    expected_candidate_count: int | None = None,
) -> GroupSplitResult:
    """Load and verify exact identity, text, label, and partition membership."""

    if not path.is_absolute():
        raise PrivateSplitAssignmentError(
            "the private split assignment path must be absolute"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PrivateSplitAssignmentError(
            "the private split assignment is invalid"
        ) from exc
    if not isinstance(payload, Mapping):
        raise PrivateSplitAssignmentError(
            "the private split assignment must contain an object"
        )
    expected_fields = {
        "version",
        "private",
        "contains_source_identifiers",
        "shareable",
        "label_set_version",
        "random_state",
        "candidate_count",
        "candidate_seed",
        "balance_score",
        "evaluated_candidate_count",
        "fallback_used",
        "records",
    }
    if (
        set(payload) != expected_fields
        or payload.get("version") != PRIVATE_SPLIT_ASSIGNMENT_VERSION
        or payload.get("private") is not True
        or payload.get("contains_source_identifiers") is not True
        or payload.get("shareable") is not False
        or payload.get("label_set_version") != expected_label_set_version
    ):
        raise PrivateSplitAssignmentError(
            "the private split assignment metadata is invalid"
        )
    if (
        expected_random_state is not None
        and payload.get("random_state") != expected_random_state
    ) or (
        expected_candidate_count is not None
        and payload.get("candidate_count") != expected_candidate_count
    ):
        raise PrivateSplitAssignmentError(
            "the private split configuration does not match the training run"
        )
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or len(raw_records) != len(samples):
        raise PrivateSplitAssignmentError(
            "the private split assignment sample count is invalid"
        )
    indexed_samples: dict[tuple[str, str, str, str], tuple[int, EmotionSample]] = {}
    for index, sample in enumerate(samples):
        key = _sample_key(sample)
        if key in indexed_samples:
            raise PrivateSplitAssignmentError(
                "samples contain duplicate private split keys"
            )
        indexed_samples[key] = (index, sample)
    indexed_base_keys = {key[:3] for key in indexed_samples}
    partitions: dict[str, list[int]] = {name: [] for name in PARTITION_NAMES}
    seen: set[tuple[str, str, str, str]] = set()
    record_fields = {
        "official_split",
        "profile_id",
        "talk_id",
        "label",
        "text_sha256",
        "partition",
    }
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping) or set(raw_record) != record_fields:
            raise PrivateSplitAssignmentError(
                "a private split assignment record is invalid"
            )
        values = (
            raw_record.get("official_split"),
            raw_record.get("profile_id"),
            raw_record.get("talk_id"),
            raw_record.get("label"),
            raw_record.get("text_sha256"),
            raw_record.get("partition"),
        )
        if not all(isinstance(value, str) and value for value in values):
            raise PrivateSplitAssignmentError(
                "a private split assignment record is invalid"
            )
        typed_values = cast(tuple[str, str, str, str, str, str], values)
        key = (
            typed_values[0],
            typed_values[1],
            typed_values[2],
            typed_values[4],
        )
        if key in seen:
            raise PrivateSplitAssignmentError(
                "private split membership does not match prepared samples"
            )
        if key not in indexed_samples:
            if key[:3] in indexed_base_keys:
                raise PrivateSplitAssignmentError(
                    "private split content does not match prepared samples"
                )
            raise PrivateSplitAssignmentError(
                "private split membership does not match prepared samples"
            )
        seen.add(key)
        index, sample = indexed_samples[key]
        if typed_values[3] != sample.label or typed_values[4] != _text_digest(sample):
            raise PrivateSplitAssignmentError(
                "private split content does not match prepared samples"
            )
        partition = typed_values[5]
        if partition not in partitions:
            raise PrivateSplitAssignmentError("a private split partition is invalid")
        partitions[partition].append(index)
    if seen != set(indexed_samples) or not all(partitions.values()):
        raise PrivateSplitAssignmentError(
            "private split membership does not cover prepared samples"
        )

    candidate_seed = payload.get("candidate_seed")
    balance_score = payload.get("balance_score")
    evaluated_candidate_count = payload.get("evaluated_candidate_count")
    fallback_used = payload.get("fallback_used")
    if (
        not isinstance(candidate_seed, int)
        or not isinstance(balance_score, (int, float))
        or not isinstance(evaluated_candidate_count, int)
        or evaluated_candidate_count < 1
        or not isinstance(fallback_used, bool)
    ):
        raise PrivateSplitAssignmentError(
            "the private split selection metadata is invalid"
        )
    all_labels = {sample.label for sample in samples}
    validation_labels = {samples[index].label for index in partitions["validation"]}
    test_labels = {samples[index].label for index in partitions["test"]}
    return GroupSplitResult(
        train_indices=tuple(partitions["train"]),
        validation_indices=tuple(partitions["validation"]),
        test_indices=tuple(partitions["test"]),
        candidate_seed=candidate_seed,
        balance_score=float(balance_score),
        missing_validation_classes=tuple(sorted(all_labels - validation_labels)),
        missing_test_classes=tuple(sorted(all_labels - test_labels)),
        evaluated_candidate_count=evaluated_candidate_count,
        fallback_used=fallback_used,
    )
