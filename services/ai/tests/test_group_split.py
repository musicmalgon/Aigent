"""Synthetic-only tests for profile-isolated candidate split selection."""

from __future__ import annotations

import json
from typing import cast

import ai.src.remind_ai.data.group_split as group_split_module
import pytest
from ai.src.remind_ai.data.emotion_dataset import EmotionSample
from ai.src.remind_ai.data.group_split import (
    GroupSplitError,
    select_group_safe_split,
    split_leakage_statistics,
)


def _samples() -> list[EmotionSample]:
    samples: list[EmotionSample] = []
    for group_index in range(8):
        for label in ("SYNTH_A", "SYNTH_B"):
            samples.append(
                EmotionSample(
                    text=f"Synthetic text group {group_index} label {label}",
                    label=label,
                    sample_id=f"PRIVATE-REUSED-TALK-{label}",
                    group_id=f"PRIVATE-PROFILE-{group_index}",
                    official_split="official_train",
                )
            )
    return samples


def _overlap_counts(leakage: dict[str, object], name: str) -> dict[str, int]:
    counts = leakage[name]
    assert isinstance(counts, dict)
    return cast(dict[str, int], counts)


def test_group_split_is_reproducible_isolated_and_balanced() -> None:
    samples = _samples()
    single_candidate = select_group_safe_split(
        samples, random_state=42, candidate_count=1
    )
    first = select_group_safe_split(samples, random_state=42, candidate_count=30)
    second = select_group_safe_split(samples, random_state=42, candidate_count=30)
    assert first == second
    split_samples = {
        name: first.samples_for(samples, name)
        for name in ("train", "validation", "test")
    }
    leakage = split_leakage_statistics(split_samples)
    assert all(
        value == 0
        for value in _overlap_counts(leakage, "profile_id_overlap_count").values()
    )
    assert all(
        value == 0
        for value in _overlap_counts(leakage, "conversation_key_overlap_count").values()
    )
    assert any(
        value > 0
        for value in _overlap_counts(leakage, "raw_talk_id_overlap_count").values()
    )
    assert leakage["raw_talk_id_overlap_is_blocking"] is False
    assert {sample.label for sample in split_samples["train"]} == {"SYNTH_A", "SYNTH_B"}
    assert first.balance_score >= 0.0
    assert first.balance_score <= single_candidate.balance_score


def test_reused_raw_talk_ids_do_not_block_profile_safe_split() -> None:
    samples = _samples()
    result = select_group_safe_split(samples, random_state=7, candidate_count=20)
    split_samples = {
        name: result.samples_for(samples, name)
        for name in ("train", "validation", "test")
    }
    leakage = split_leakage_statistics(split_samples)
    assert all(
        value == 0
        for value in _overlap_counts(leakage, "profile_id_overlap_count").values()
    )
    assert all(
        value == 0
        for value in _overlap_counts(leakage, "conversation_key_overlap_count").values()
    )
    assert any(
        value > 0
        for value in _overlap_counts(leakage, "raw_talk_id_overlap_count").values()
    )


def test_validation_and_test_missing_classes_are_scored_not_rejected() -> None:
    samples = [
        EmotionSample(
            text=f"Synthetic text {index}",
            label="SYNTH_A" if index % 2 else "SYNTH_B",
            sample_id="PRIVATE-REUSED-RAW-TALK",
            group_id=f"PRIVATE-PROFILE-{index}",
            official_split="official_train",
        )
        for index in range(6)
    ]
    result = select_group_safe_split(samples, random_state=42, candidate_count=30)
    assert result.missing_validation_classes
    assert result.missing_test_classes


def test_uses_1000_candidate_fallback_when_initial_200_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = _samples()

    def delayed_candidate(
        source: list[EmotionSample], seed: int
    ) -> tuple[list[int], list[int], list[int]]:
        del source
        if seed < 242:
            raise ValueError("synthetic candidate miss")
        return list(range(12)), [12, 13], [14, 15]

    monkeypatch.setattr(group_split_module, "_candidate_partitions", delayed_candidate)
    result = select_group_safe_split(samples, random_state=42, candidate_count=200)
    assert result.fallback_used is True
    assert result.candidate_seed == 242
    assert result.evaluated_candidate_count == 1_000


def test_impossible_split_exposes_only_safe_aggregate_diagnostics() -> None:
    samples = [
        EmotionSample(
            text="PRIVATE TEXT",
            label="SYNTH_A" if index else "SYNTH_B",
            sample_id="PRIVATE TALK",
            group_id="PRIVATE PROFILE",
            official_split="official_train",
        )
        for index in range(2)
    ]
    with pytest.raises(GroupSplitError) as error:
        select_group_safe_split(samples)
    serialized = json.dumps(error.value.diagnostics)
    assert "PRIVATE" not in serialized
    dataset = error.value.diagnostics["dataset"]
    assert isinstance(dataset, dict)
    assert dataset["record_count"] == 2


def test_too_few_groups_fails_safely() -> None:
    samples = _samples()[:4]
    with pytest.raises(GroupSplitError):
        select_group_safe_split(samples)


def test_strict_split_requires_every_class_in_validation_and_test() -> None:
    labels = ("분노", "기쁨", "불안", "당황", "슬픔", "무기력")
    samples = [
        EmotionSample(
            text=f"UNIQUE SYNTHETIC {profile} {label_index}",
            label=label,
            sample_id=f"TALK-{profile}-{label_index}",
            group_id=f"PROFILE-{profile}",
            official_split="synthetic",
        )
        for profile in range(6)
        for label_index, label in enumerate(labels)
    ]
    split = select_group_safe_split(
        samples,
        random_state=42,
        candidate_count=20,
        require_evaluation_class_coverage=True,
        require_normalized_text_isolation=True,
    )
    for name in ("train", "validation", "test"):
        assert {sample.label for sample in split.samples_for(samples, name)} == set(
            labels
        )


def test_strict_split_rejects_class_with_fewer_than_three_profiles() -> None:
    samples = [
        EmotionSample(
            text=f"UNIQUE A {profile}",
            label="A",
            sample_id=f"A-{profile}",
            group_id=f"PROFILE-{profile}",
            official_split="synthetic",
        )
        for profile in range(4)
    ]
    samples.extend(
        EmotionSample(
            text=f"UNIQUE B {profile}",
            label="B",
            sample_id=f"B-{profile}",
            group_id=f"PROFILE-{profile}",
            official_split="synthetic",
        )
        for profile in range(2)
    )
    with pytest.raises(GroupSplitError, match="three profile groups"):
        select_group_safe_split(
            samples,
            require_evaluation_class_coverage=True,
        )
