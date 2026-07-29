"""Reviewed overlay for the Re:Mind six-class v2 emotion taxonomy.

The source AI Hub taxonomy remains immutable.  This module first resolves its
official coarse label and then applies a local, human-reviewed decision
manifest.  Source text and identifiers are never included in reports.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from .emotion_dataset import EmotionSample
from .emotion_label_mapping import EmotionLabelMapping

REMIND_COARSE_V2 = "remind-coarse-v2"
EXPECTED_V2_LABELS = ("분노", "기쁨", "불안", "당황", "슬픔", "무기력")
EXPECTED_REMOVED_LABEL = "상처"
EXPECTED_POLICY_VERSION = 2
EXPECTED_FINE_LABEL_OVERRIDES = {"E25": "무기력", "E28": "무기력"}
APPROVED_REVIEW_STATUS = "approved"
ANNOTATION_DECISIONS = frozenset({"exclude", "relabel"})
OFFICIAL_SPLITS = frozenset({"official_train", "official_validation"})
OPAQUE_DATASET_RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class EmotionTaxonomyV2Error(ValueError):
    """Raised with a value-safe message for an invalid policy or manifest."""


@dataclass(frozen=True)
class EmotionLabelPolicyV2:
    """Validated, reviewable definition of the replacement label set."""

    version: int
    label_set_version: str
    labels: tuple[str, ...]
    base_label_mapping: str
    excluded_base_labels: tuple[str, ...]
    fine_label_overrides: Mapping[str, str]
    definitions: Mapping[str, str]


@dataclass(frozen=True)
class AnnotationDecision:
    """One approved decision keyed without using source text."""

    official_split: str
    profile_id: str
    talk_id: str
    source_fine_label: str
    source_text_sha256: str
    decision: str
    label: str | None

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.official_split,
            self.profile_id,
            self.talk_id,
            self.source_text_sha256,
        )


@dataclass(frozen=True)
class AnnotationManifest:
    """Local reviewed decisions for records affected by the v2 taxonomy."""

    version: int
    label_set_version: str
    dataset_release_id: str
    annotation_revision: int
    decisions: Mapping[tuple[str, str, str, str], AnnotationDecision]


@dataclass(frozen=True)
class PreparedTaxonomyV2:
    """Prepared samples and an aggregate-only audit report."""

    samples: tuple[EmotionSample, ...]
    report: Mapping[str, object]


def _load_json_object(path: Path, kind: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EmotionTaxonomyV2Error(f"{kind} file is invalid") from exc
    if not isinstance(payload, Mapping):
        raise EmotionTaxonomyV2Error(f"{kind} file must contain an object")
    return payload


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EmotionTaxonomyV2Error(f"{name} must be a non-empty string")
    return value.strip()


def source_text_sha256(sample: EmotionSample) -> str:
    """Bind a reviewed decision to the exact normalized model input text."""

    return hashlib.sha256(sample.text.encode("utf-8")).hexdigest()


def validate_dataset_release_id(value: object) -> str:
    """Validate a non-sensitive source dataset release identifier."""

    parsed = _required_string(value, "dataset_release_id")
    if OPAQUE_DATASET_RELEASE_ID.fullmatch(parsed) is None:
        raise EmotionTaxonomyV2Error(
            "dataset_release_id must be a short opaque identifier"
        )
    return parsed


def _required_string_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise EmotionTaxonomyV2Error(f"{name} must be a string list")
    parsed = tuple(_required_string(item, name) for item in value)
    if not parsed:
        raise EmotionTaxonomyV2Error(f"{name} must not be empty")
    return parsed


def load_emotion_label_policy_v2(path: Path) -> EmotionLabelPolicyV2:
    """Load the committed v2 label definition and reject semantic drift."""

    payload = _load_json_object(path, "label policy")
    expected_keys = {
        "version",
        "label_set_version",
        "labels",
        "base_label_mapping",
        "excluded_base_labels",
        "default_unreviewed_action",
        "fine_label_overrides",
        "annotation_key_fields",
        "required_review_status",
        "definitions",
    }
    if set(payload) != expected_keys:
        raise EmotionTaxonomyV2Error("label policy fields are invalid")
    version = payload.get("version")
    label_set_version = payload.get("label_set_version")
    labels = _required_string_list(payload.get("labels"), "policy labels")
    excluded = _required_string_list(
        payload.get("excluded_base_labels"), "excluded base labels"
    )
    if (
        version != EXPECTED_POLICY_VERSION
        or label_set_version != REMIND_COARSE_V2
        or labels != EXPECTED_V2_LABELS
        or excluded != (EXPECTED_REMOVED_LABEL,)
        or payload.get("base_label_mapping") != "official-coarse-v1"
        or payload.get("default_unreviewed_action") != "keep_base_unless_excluded"
        or payload.get("fine_label_overrides") != EXPECTED_FINE_LABEL_OVERRIDES
        or payload.get("annotation_key_fields")
        != [
            "official_split",
            "profile_id",
            "talk_id",
            "source_text_sha256",
        ]
        or payload.get("required_review_status") != APPROVED_REVIEW_STATUS
    ):
        raise EmotionTaxonomyV2Error("label policy does not define remind-coarse-v2")
    raw_definitions = payload.get("definitions")
    if not isinstance(raw_definitions, Mapping) or set(raw_definitions) != set(labels):
        raise EmotionTaxonomyV2Error("label policy definitions are invalid")
    definitions = {
        label: _required_string(raw_definitions[label], "label definition")
        for label in labels
    }
    return EmotionLabelPolicyV2(
        version=version,
        label_set_version=label_set_version,
        labels=labels,
        base_label_mapping="official-coarse-v1",
        excluded_base_labels=excluded,
        fine_label_overrides=dict(EXPECTED_FINE_LABEL_OVERRIDES),
        definitions=definitions,
    )


def load_annotation_manifest(
    path: Path, policy: EmotionLabelPolicyV2
) -> AnnotationManifest:
    """Load a strict local manifest containing only approved decisions."""

    payload = _load_json_object(path, "annotation manifest")
    if set(payload) != {
        "version",
        "label_set_version",
        "dataset_release_id",
        "annotation_revision",
        "records",
    }:
        raise EmotionTaxonomyV2Error("annotation manifest fields are invalid")
    if payload.get("version") != 1:
        raise EmotionTaxonomyV2Error("annotation manifest version is invalid")
    if payload.get("label_set_version") != policy.label_set_version:
        raise EmotionTaxonomyV2Error("annotation manifest label set is invalid")
    dataset_release_id = validate_dataset_release_id(payload.get("dataset_release_id"))
    annotation_revision = payload.get("annotation_revision")
    if (
        not isinstance(annotation_revision, int)
        or isinstance(annotation_revision, bool)
        or annotation_revision < 1
    ):
        raise EmotionTaxonomyV2Error("annotation revision must be a positive integer")
    records = payload.get("records")
    if not isinstance(records, list):
        raise EmotionTaxonomyV2Error("annotation manifest records must be a list")
    decisions: dict[tuple[str, str, str, str], AnnotationDecision] = {}
    for raw_record in records:
        if not isinstance(raw_record, Mapping):
            raise EmotionTaxonomyV2Error("an annotation manifest record is invalid")
        decision = raw_record.get("decision")
        expected = {
            "official_split",
            "profile_id",
            "talk_id",
            "decision",
            "review_status",
            "source_fine_label",
            "source_text_sha256",
        }
        if decision == "relabel":
            expected.add("label")
        if set(raw_record) != expected:
            raise EmotionTaxonomyV2Error(
                "an annotation manifest record has invalid fields"
            )
        official_split = _required_string(
            raw_record.get("official_split"), "annotation official_split"
        )
        profile_id = _required_string(
            raw_record.get("profile_id"), "annotation profile_id"
        )
        talk_id = _required_string(raw_record.get("talk_id"), "annotation talk_id")
        source_fine_label = _required_string(
            raw_record.get("source_fine_label"), "annotation source_fine_label"
        )
        source_text_digest = _required_string(
            raw_record.get("source_text_sha256"), "annotation source_text_sha256"
        )
        if SHA256_HEX.fullmatch(source_text_digest) is None:
            raise EmotionTaxonomyV2Error(
                "annotation source_text_sha256 must be a lowercase SHA-256 digest"
            )
        if official_split not in OFFICIAL_SPLITS:
            raise EmotionTaxonomyV2Error("annotation official_split is invalid")
        if raw_record.get("review_status") != APPROVED_REVIEW_STATUS:
            raise EmotionTaxonomyV2Error("every annotation decision must be approved")
        if decision not in ANNOTATION_DECISIONS:
            raise EmotionTaxonomyV2Error("annotation decision is invalid")
        label: str | None = None
        if decision == "relabel":
            label = _required_string(raw_record.get("label"), "annotation label")
            if label not in policy.labels:
                raise EmotionTaxonomyV2Error(
                    "annotation label is outside the v2 policy"
                )
        parsed = AnnotationDecision(
            official_split=official_split,
            profile_id=profile_id,
            talk_id=talk_id,
            source_fine_label=source_fine_label,
            source_text_sha256=source_text_digest,
            decision=decision,
            label=label,
        )
        if parsed.key in decisions:
            raise EmotionTaxonomyV2Error("annotation manifest contains a duplicate key")
        decisions[parsed.key] = parsed
    return AnnotationManifest(
        version=1,
        label_set_version=policy.label_set_version,
        dataset_release_id=dataset_release_id,
        annotation_revision=annotation_revision,
        decisions=decisions,
    )


def prepare_remind_coarse_v2(
    samples: Sequence[EmotionSample],
    official_mapping: EmotionLabelMapping,
    policy: EmotionLabelPolicyV2,
    manifest: AnnotationManifest | None = None,
    *,
    dataset_release_id: str | None = None,
) -> PreparedTaxonomyV2:
    """Apply deterministic fine-label regrouping and optional reviewed decisions."""

    if manifest is not None and manifest.label_set_version != policy.label_set_version:
        raise EmotionTaxonomyV2Error("annotation manifest and policy do not match")
    resolved_dataset_release_id = (
        manifest.dataset_release_id
        if manifest is not None
        else (
            validate_dataset_release_id(dataset_release_id)
            if dataset_release_id is not None
            else None
        )
    )
    if (
        manifest is not None
        and dataset_release_id is not None
        and manifest.dataset_release_id != validate_dataset_release_id(dataset_release_id)
    ):
        raise EmotionTaxonomyV2Error(
            "annotation manifest and dataset release do not match"
        )
    if not samples:
        raise EmotionTaxonomyV2Error("the source dataset is empty")
    sample_keys = [
        (
            sample.official_split,
            sample.group_id,
            sample.sample_id,
            source_text_sha256(sample),
        )
        for sample in samples
    ]
    if len(set(sample_keys)) != len(sample_keys):
        raise EmotionTaxonomyV2Error(
            "the source dataset contains duplicate annotation keys"
        )
    manifest_decisions = manifest.decisions if manifest is not None else {}
    unknown_manifest_keys = set(manifest_decisions) - set(sample_keys)
    if unknown_manifest_keys:
        sample_base_keys = {key[:3] for key in sample_keys}
        if any(key[:3] in sample_base_keys for key in unknown_manifest_keys):
            raise EmotionTaxonomyV2Error(
                "annotation source text does not match the source dataset"
            )
        raise EmotionTaxonomyV2Error(
            "annotation manifest contains records outside the source dataset"
        )

    final_samples: list[EmotionSample] = []
    action_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    final_counts: Counter[str] = Counter()
    final_profiles: dict[str, set[str]] = {label: set() for label in policy.labels}
    decision_label_counts: Counter[str] = Counter()
    for sample, key in zip(samples, sample_keys, strict=True):
        fine_label = official_mapping.fine_to_coarse.get(sample.label)
        if fine_label is None:
            raise EmotionTaxonomyV2Error(
                "the source dataset contains an unmapped fine label"
            )
        source_label = fine_label.coarse_name
        source_counts[source_label] += 1
        annotation = manifest_decisions.get(key)
        if annotation is not None and annotation.source_fine_label != sample.label:
            raise EmotionTaxonomyV2Error(
                "annotation source label does not match the source dataset"
            )
        if (
            annotation is not None
            and annotation.source_text_sha256 != source_text_sha256(sample)
        ):
            raise EmotionTaxonomyV2Error(
                "annotation source text does not match the source dataset"
            )
        if annotation is not None and annotation.decision == "exclude":
            action_counts["excluded_by_review"] += 1
            continue
        if annotation is not None and annotation.decision == "relabel":
            assert annotation.label is not None
            final_label = annotation.label
            action_counts["relabeled_by_review"] += 1
            decision_label_counts[final_label] += 1
        elif sample.label in policy.fine_label_overrides:
            final_label = policy.fine_label_overrides[sample.label]
            action_counts["remapped_by_fine_label_policy"] += 1
        elif source_label in policy.excluded_base_labels:
            action_counts["excluded_removed_base_label"] += 1
            continue
        else:
            final_label = source_label
            action_counts["kept_from_official_mapping"] += 1
        if final_label not in policy.labels:
            raise EmotionTaxonomyV2Error("the prepared label is outside the v2 policy")
        final_counts[final_label] += 1
        final_profiles[final_label].add(sample.group_id)
        final_samples.append(replace(sample, label=final_label))

    if set(final_counts) != set(policy.labels):
        raise EmotionTaxonomyV2Error(
            "the prepared v2 dataset does not contain all six required labels"
        )
    if final_counts["무기력"] < 1:
        raise EmotionTaxonomyV2Error(
            "the prepared v2 dataset has no approved lethargy samples"
        )
    report: dict[str, object] = {
        "policy_version": policy.version,
        "label_set_version": policy.label_set_version,
        "dataset_release_id": resolved_dataset_release_id,
        "annotation_revision": (
            manifest.annotation_revision if manifest is not None else None
        ),
        "mapping_strategy": "deterministic_fine_label_regrouping",
        "fine_label_overrides": dict(policy.fine_label_overrides),
        "labels": list(policy.labels),
        "removed_base_labels": list(policy.excluded_base_labels),
        "source_sample_count": len(samples),
        "prepared_sample_count": len(final_samples),
        "source_class_counts": dict(sorted(source_counts.items())),
        "prepared_class_counts": {
            label: final_counts[label] for label in policy.labels
        },
        "prepared_class_profile_counts": {
            label: len(final_profiles[label]) for label in policy.labels
        },
        "action_counts": dict(sorted(action_counts.items())),
        "approved_decision_count": len(manifest_decisions),
        "approved_relabel_counts": dict(sorted(decision_label_counts.items())),
        "unreviewed_removed_label_is_excluded": True,
        "source_text_or_identifiers_serialized": False,
    }
    return PreparedTaxonomyV2(samples=tuple(final_samples), report=report)


def safe_policy_payload(policy: EmotionLabelPolicyV2) -> dict[str, object]:
    """Return the committed policy without local annotation identifiers."""

    return {
        "version": policy.version,
        "label_set_version": policy.label_set_version,
        "labels": list(policy.labels),
        "base_label_mapping": policy.base_label_mapping,
        "excluded_base_labels": list(policy.excluded_base_labels),
        "fine_label_overrides": dict(policy.fine_label_overrides),
        "definitions": dict(policy.definitions),
    }
