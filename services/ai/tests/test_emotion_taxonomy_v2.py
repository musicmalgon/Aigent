"""Synthetic-only tests for the reviewed Re:Mind coarse v2 overlay."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from ai.src.remind_ai.data.emotion_dataset import EmotionSample
from ai.src.remind_ai.data.emotion_label_mapping import load_emotion_label_mapping
from ai.src.remind_ai.data.emotion_taxonomy_v2 import (
    EXPECTED_V2_LABELS,
    EmotionTaxonomyV2Error,
    load_annotation_manifest,
    load_emotion_label_policy_v2,
    prepare_remind_coarse_v2,
    safe_policy_payload,
    source_text_sha256,
)

AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = AI_SERVICE_ROOT / "config" / "emotion_label_policy_v2.json"
MAPPING_PATH = AI_SERVICE_ROOT / "config" / "emotion_label_mapping.json"


def _sample(index: int, fine_label: str) -> EmotionSample:
    return EmotionSample(
        text=f"PRIVATE TEXT {index}",
        label=fine_label,
        sample_id=f"PRIVATE-TALK-{index}",
        group_id=f"PRIVATE-PROFILE-{index}",
        official_split=("official_train" if index % 2 else "official_validation"),
    )


def _manifest_record(
    sample: EmotionSample, *, decision: str, label: str | None = None
) -> dict[str, object]:
    record: dict[str, object] = {
        "official_split": sample.official_split,
        "profile_id": sample.group_id,
        "talk_id": sample.sample_id,
        "decision": decision,
        "review_status": "approved",
        "source_fine_label": sample.label,
        "source_text_sha256": source_text_sha256(sample),
    }
    if label is not None:
        record["label"] = label
    return record


def _write_manifest(
    path: Path,
    records: list[dict[str, object]],
    *,
    dataset_release_id: str = "synthetic-v2-001",
) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "label_set_version": "remind-coarse-v2",
                "dataset_release_id": dataset_release_id,
                "annotation_revision": 1,
                "records": records,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_policy_is_the_exact_replacement_six_class_vocabulary() -> None:
    policy = load_emotion_label_policy_v2(POLICY_PATH)
    assert policy.labels == EXPECTED_V2_LABELS
    assert policy.excluded_base_labels == ("상처",)
    assert policy.version == 2
    assert policy.fine_label_overrides == {"E25": "무기력", "E28": "무기력"}
    assert safe_policy_payload(policy)["definitions"]["무기력"].startswith("의욕 저하")


def test_deterministic_policy_maps_e25_e28_and_excludes_hurt_without_manifest() -> None:
    samples = [
        _sample(1, "E10"),
        _sample(2, "E60"),
        _sample(3, "E30"),
        _sample(4, "E50"),
        _sample(5, "E20"),
        _sample(6, "E25"),
        _sample(7, "E28"),
        _sample(8, "E40"),
    ]
    policy = load_emotion_label_policy_v2(POLICY_PATH)

    prepared = prepare_remind_coarse_v2(
        samples,
        load_emotion_label_mapping(MAPPING_PATH),
        policy,
        dataset_release_id="synthetic-v2-001",
    )

    assert {sample.label for sample in prepared.samples} == set(EXPECTED_V2_LABELS)
    assert all(sample.sample_id != samples[-1].sample_id for sample in prepared.samples)
    assert prepared.report["action_counts"] == {
        "excluded_removed_base_label": 1,
        "kept_from_official_mapping": 5,
        "remapped_by_fine_label_policy": 2,
    }
    assert prepared.report["mapping_strategy"] == (
        "deterministic_fine_label_regrouping"
    )
    assert prepared.report["annotation_revision"] is None


def test_reviewed_overlay_excludes_hurt_by_default_and_adds_lethargy(
    tmp_path: Path,
) -> None:
    samples = [
        _sample(1, "E10"),
        _sample(2, "E60"),
        _sample(3, "E30"),
        _sample(4, "E50"),
        _sample(5, "E20"),
        _sample(6, "E40"),
        _sample(7, "E41"),
    ]
    manifest_path = tmp_path / "private_annotations.json"
    _write_manifest(
        manifest_path,
        [_manifest_record(samples[5], decision="relabel", label="무기력")],
    )
    policy = load_emotion_label_policy_v2(POLICY_PATH)
    manifest = load_annotation_manifest(manifest_path, policy)
    prepared = prepare_remind_coarse_v2(
        samples,
        load_emotion_label_mapping(MAPPING_PATH),
        policy,
        manifest,
    )

    assert len(prepared.samples) == 6
    assert {sample.label for sample in prepared.samples} == set(EXPECTED_V2_LABELS)
    assert all(sample.sample_id != samples[6].sample_id for sample in prepared.samples)
    assert prepared.report["action_counts"] == {
        "excluded_removed_base_label": 1,
        "kept_from_official_mapping": 5,
        "relabeled_by_review": 1,
    }
    serialized = json.dumps(prepared.report, ensure_ascii=False)
    assert "PRIVATE-TALK" not in serialized
    assert "PRIVATE-PROFILE" not in serialized
    assert "PRIVATE TEXT" not in serialized


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"review_status": "draft"}, "approved"),
        ({"label": "상처"}, "outside"),
        ({"source_text_sha256": "not-a-digest"}, "SHA-256"),
        ({"unexpected": True}, "fields"),
    ],
)
def test_manifest_rejects_unapproved_unknown_or_extra_values(
    tmp_path: Path,
    mutation: dict[str, object],
    message: str,
) -> None:
    sample = _sample(1, "E40")
    record = _manifest_record(sample, decision="relabel", label="무기력")
    record.update(mutation)
    manifest_path = tmp_path / "invalid.json"
    _write_manifest(manifest_path, [record])
    policy = load_emotion_label_policy_v2(POLICY_PATH)

    with pytest.raises(EmotionTaxonomyV2Error, match=message):
        load_annotation_manifest(manifest_path, policy)


def test_manifest_record_outside_dataset_is_rejected_without_identifier(
    tmp_path: Path,
) -> None:
    samples = [
        _sample(1, "E10"),
        _sample(2, "E60"),
        _sample(3, "E30"),
        _sample(4, "E50"),
        _sample(5, "E20"),
        _sample(6, "E40"),
    ]
    outside = _sample(99, "E40")
    manifest_path = tmp_path / "outside.json"
    _write_manifest(
        manifest_path,
        [_manifest_record(outside, decision="relabel", label="무기력")],
    )
    policy = load_emotion_label_policy_v2(POLICY_PATH)
    manifest = load_annotation_manifest(manifest_path, policy)

    with pytest.raises(EmotionTaxonomyV2Error) as captured:
        prepare_remind_coarse_v2(
            samples,
            load_emotion_label_mapping(MAPPING_PATH),
            policy,
            manifest,
        )
    assert outside.sample_id not in str(captured.value)
    assert outside.group_id not in str(captured.value)


def test_manifest_duplicate_key_is_rejected(tmp_path: Path) -> None:
    sample = _sample(1, "E40")
    record = _manifest_record(sample, decision="relabel", label="무기력")
    manifest_path = tmp_path / "duplicate.json"
    _write_manifest(manifest_path, [record, record])
    policy = load_emotion_label_policy_v2(POLICY_PATH)

    with pytest.raises(EmotionTaxonomyV2Error, match="duplicate"):
        load_annotation_manifest(manifest_path, policy)


def test_stale_source_fine_label_is_rejected(tmp_path: Path) -> None:
    samples = [
        _sample(1, "E10"),
        _sample(2, "E60"),
        _sample(3, "E30"),
        _sample(4, "E50"),
        _sample(5, "E20"),
        _sample(6, "E40"),
    ]
    record = _manifest_record(samples[5], decision="relabel", label="무기력")
    record["source_fine_label"] = "E41"
    manifest_path = tmp_path / "stale.json"
    _write_manifest(manifest_path, [record])
    policy = load_emotion_label_policy_v2(POLICY_PATH)
    manifest = load_annotation_manifest(manifest_path, policy)

    with pytest.raises(EmotionTaxonomyV2Error, match="source label"):
        prepare_remind_coarse_v2(
            samples,
            load_emotion_label_mapping(MAPPING_PATH),
            policy,
            manifest,
        )


def test_stale_source_text_is_rejected(tmp_path: Path) -> None:
    samples = [
        _sample(1, "E10"),
        _sample(2, "E60"),
        _sample(3, "E30"),
        _sample(4, "E50"),
        _sample(5, "E20"),
        _sample(6, "E40"),
    ]
    record = _manifest_record(samples[5], decision="relabel", label="무기력")
    manifest_path = tmp_path / "stale-text.json"
    _write_manifest(manifest_path, [record])
    policy = load_emotion_label_policy_v2(POLICY_PATH)
    manifest = load_annotation_manifest(manifest_path, policy)
    changed = [*samples[:-1], replace(samples[-1], text="CHANGED PRIVATE TEXT")]

    with pytest.raises(EmotionTaxonomyV2Error, match="source text"):
        prepare_remind_coarse_v2(
            changed,
            load_emotion_label_mapping(MAPPING_PATH),
            policy,
            manifest,
        )


@pytest.mark.parametrize(
    "dataset_release_id",
    [
        "C:/private/dataset.json",
        "../private",
        "contains spaces",
        "x" * 65,
    ],
)
def test_manifest_rejects_non_opaque_dataset_release_id(
    tmp_path: Path, dataset_release_id: str
) -> None:
    sample = _sample(1, "E40")
    manifest_path = tmp_path / "unsafe-release-id.json"
    _write_manifest(
        manifest_path,
        [_manifest_record(sample, decision="relabel", label="무기력")],
        dataset_release_id=dataset_release_id,
    )

    with pytest.raises(EmotionTaxonomyV2Error, match="opaque identifier"):
        load_annotation_manifest(
            manifest_path, load_emotion_label_policy_v2(POLICY_PATH)
        )
