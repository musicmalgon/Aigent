"""Tests for exact local-only TF-IDF/Transformer split reuse."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai.src.remind_ai.data.emotion_dataset import EmotionSample
from ai.src.remind_ai.data.group_split import select_group_safe_split
from ai.src.remind_ai.data.private_split_assignment import (
    PrivateSplitAssignmentError,
    load_private_split_assignment,
    write_private_split_assignment,
)


def _samples() -> list[EmotionSample]:
    return [
        EmotionSample(
            text=f"PRIVATE TEXT {index}",
            label="분노" if index % 2 else "기쁨",
            sample_id=f"PRIVATE-TALK-{index}",
            group_id=f"PRIVATE-PROFILE-{index}",
            official_split=("official_train" if index < 6 else "official_validation"),
        )
        for index in range(10)
    ]


def test_private_assignment_reuses_exact_membership(tmp_path: Path) -> None:
    samples = _samples()
    selected = select_group_safe_split(samples, random_state=42, candidate_count=20)
    path = tmp_path / "private" / "split_assignment.json"
    write_private_split_assignment(
        path,
        samples,
        selected,
        label_set_version="remind-coarse-v2",
        random_state=42,
        candidate_count=20,
    )

    loaded = load_private_split_assignment(
        path,
        list(reversed(samples)),
        expected_label_set_version="remind-coarse-v2",
    )
    expected_train_keys = {
        (samples[index].group_id, samples[index].sample_id)
        for index in selected.train_indices
    }
    reversed_samples = list(reversed(samples))
    actual_train_keys = {
        (reversed_samples[index].group_id, reversed_samples[index].sample_id)
        for index in loaded.train_indices
    }
    assert actual_train_keys == expected_train_keys


@pytest.mark.parametrize(
    ("field", "replacement"), [("label", "불안"), ("text_sha256", "0" * 64)]
)
def test_private_assignment_detects_label_or_text_change(
    tmp_path: Path, field: str, replacement: str
) -> None:
    samples = _samples()
    selected = select_group_safe_split(samples, random_state=42, candidate_count=20)
    path = tmp_path / "split_assignment.json"
    write_private_split_assignment(
        path,
        samples,
        selected,
        label_set_version="remind-coarse-v2",
        random_state=42,
        candidate_count=20,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["records"][0][field] = replacement
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PrivateSplitAssignmentError, match="content"):
        load_private_split_assignment(
            path,
            samples,
            expected_label_set_version="remind-coarse-v2",
        )


def test_private_assignment_errors_do_not_echo_identifiers(tmp_path: Path) -> None:
    samples = _samples()
    selected = select_group_safe_split(samples, random_state=42, candidate_count=20)
    path = tmp_path / "split_assignment.json"
    write_private_split_assignment(
        path,
        samples,
        selected,
        label_set_version="remind-coarse-v2",
        random_state=42,
        candidate_count=20,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    private_id = payload["records"][0]["talk_id"]
    payload["records"][0]["talk_id"] = "UNKNOWN-PRIVATE-ID"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PrivateSplitAssignmentError) as captured:
        load_private_split_assignment(
            path,
            samples,
            expected_label_set_version="remind-coarse-v2",
        )
    assert private_id not in str(captured.value)
    assert "UNKNOWN-PRIVATE-ID" not in str(captured.value)


def test_private_assignment_rejects_split_configuration_mismatch(
    tmp_path: Path,
) -> None:
    samples = _samples()
    selected = select_group_safe_split(samples, random_state=42, candidate_count=20)
    path = tmp_path / "split_assignment.json"
    write_private_split_assignment(
        path,
        samples,
        selected,
        label_set_version="remind-coarse-v2",
        random_state=42,
        candidate_count=20,
    )

    with pytest.raises(PrivateSplitAssignmentError, match="configuration"):
        load_private_split_assignment(
            path,
            samples,
            expected_label_set_version="remind-coarse-v2",
            expected_random_state=7,
            expected_candidate_count=20,
        )


def test_private_assignment_distinguishes_reused_ids_by_text_digest(
    tmp_path: Path,
) -> None:
    samples = _samples()
    original = samples[0]
    samples.append(
        EmotionSample(
            text="DIFFERENT PRIVATE TEXT",
            label=original.label,
            sample_id=original.sample_id,
            group_id=original.group_id,
            official_split=original.official_split,
        )
    )
    selected = select_group_safe_split(samples, random_state=42, candidate_count=20)
    path = tmp_path / "split_assignment.json"
    write_private_split_assignment(
        path,
        samples,
        selected,
        label_set_version="remind-coarse-v2",
        random_state=42,
        candidate_count=20,
    )

    loaded = load_private_split_assignment(
        path,
        samples,
        expected_label_set_version="remind-coarse-v2",
    )
    assert sum(
        len(indices)
        for indices in (
            loaded.train_indices,
            loaded.validation_indices,
            loaded.test_indices,
        )
    ) == len(samples)
