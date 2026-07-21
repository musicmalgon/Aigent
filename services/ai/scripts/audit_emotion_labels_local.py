"""Privacy-preserving local audit for the approved emotional-dialogue JSON schema.

The command is designed for a user to run locally.  It serializes only label
and situation categories plus aggregate counts; dialogue text and identifiers
remain in process memory solely while aggregate comparisons are calculated.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn


AUDIT_VERSION = "emotion-label-audit-v1"
TYPE_PATH = "$.profile.emotion.type"
EMOTION_ID_PATH = "$.profile.emotion.emotion-id"
SITUATION_PATH = "$.profile.emotion.situation"
TALK_ID_PATH = "$.talk.id.talk-id"
PROFILE_ID_PATH = "$.talk.id.profile-id"
USER_UTTERANCE_PATHS = tuple(f"$.talk.content.HS0{index}" for index in range(1, 4))
SYSTEM_RESPONSE_PATHS = tuple(f"$.talk.content.SS0{index}" for index in range(1, 4))


class AuditFailure(RuntimeError):
    """A caller-safe failure that excludes input paths and source values."""


@dataclass
class LengthStatistics:
    counts: Counter[int] = field(default_factory=Counter)

    def add(self, value: str) -> None:
        self.counts[len(value)] += 1

    def summary(self) -> dict[str, int | float | None]:
        count = sum(self.counts.values())
        if count == 0:
            return {
                "count": 0,
                "min": None,
                "max": None,
                "mean": None,
                "p50": None,
                "p95": None,
            }
        return {
            "count": count,
            "min": min(self.counts),
            "max": max(self.counts),
            "mean": round(
                sum(length * frequency for length, frequency in self.counts.items())
                / count,
                3,
            ),
            "p50": float(_quantile(self.counts, 0.50)),
            "p95": float(_quantile(self.counts, 0.95)),
        }


@dataclass
class SplitInternal:
    talk_ids: Counter[str]
    profile_ids: Counter[str]
    exact_texts: Counter[str]
    normalized_texts: Counter[str]
    normalized_text_labels: dict[str, set[tuple[str | None, str | None]]]
    type_labels: set[str]
    emotion_id_labels: set[str]


def _quantile(counts: Counter[int], fraction: float) -> int:
    total = sum(counts.values())
    rank = max(0, math.ceil(total * fraction) - 1)
    seen = 0
    for value, frequency in sorted(counts.items()):
        seen += frequency
        if seen > rank:
            return value
    raise AuditFailure("aggregate length statistics could not be calculated")


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _canonical_category(value: object, field_name: str) -> str | None:
    if _is_missing(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    raise AuditFailure(f"the approved {field_name} field has an unsupported value type")


def _get_path(record: Mapping[str, object], path: str) -> tuple[bool, object | None]:
    current: object = record
    for segment in path.removeprefix("$.").split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return False, None
        current = current[segment]
    return True, current


def _distribution(values: Sequence[str | None]) -> tuple[dict[str, object], set[str]]:
    counts: Counter[str] = Counter(value for value in values if value is not None)
    non_null_count = sum(counts.values())
    class_count = len(counts)
    frequencies = dict(sorted(counts.items()))
    ratios = {
        label: round(count / non_null_count, 6) if non_null_count else 0.0
        for label, count in frequencies.items()
    }
    frequencies_only = list(frequencies.values())
    return (
        {
            "unique_values": sorted(counts),
            "class_count": class_count,
            "class_frequencies": frequencies,
            "class_ratios": ratios,
            "null_count": len(values) - non_null_count,
            "non_null_count": non_null_count,
            "minimum_class_frequency": min(frequencies_only)
            if frequencies_only
            else None,
            "class_imbalance_ratio": round(
                max(frequencies_only) / min(frequencies_only), 6
            )
            if frequencies_only
            else None,
        },
        set(counts),
    )


def _field_presence_summary(
    records: Sequence[Mapping[str, object]],
    paths: Sequence[str],
    *,
    require_strings: bool,
) -> tuple[dict[str, object], list[list[str]]]:
    fields: dict[str, object] = {}
    per_record: list[list[str]] = []
    for _ in records:
        per_record.append([])
    for path in paths:
        present_count = 0
        null_count = 0
        for index, record in enumerate(records):
            exists, value = _get_path(record, path)
            if not exists or _is_missing(value):
                null_count += 1
                continue
            if require_strings and not isinstance(value, str):
                raise AuditFailure("an approved dialogue field has a non-string value")
            present_count += 1
            if isinstance(value, str):
                per_record[index].append(value)
        fields[path] = {
            "present_count": present_count,
            "null_count": null_count,
        }
    return fields, per_record


def _normalize_text(value: str) -> str:
    nfc = unicodedata.normalize("NFC", value)
    collapsed = re.sub(r"\s+", " ", nfc.strip())
    return re.sub(r"[A-Z]", lambda match: match.group(0).lower(), collapsed)


def _non_empty_join(parts: Sequence[str]) -> str:
    return "\n".join(part for part in parts if part.strip())


def _profile_talk_statistics(
    talk_by_profile: Mapping[str, set[str]],
) -> dict[str, object]:
    counts = Counter(len(talk_ids) for talk_ids in talk_by_profile.values())
    summary = LengthStatistics(counts=counts).summary()
    return {"profile_count": len(talk_by_profile), "talks_per_profile": summary}


def _inspect_split(
    path: Path, logical_name: str
) -> tuple[dict[str, object], SplitInternal]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuditFailure("a JSON input could not be decoded safely") from exc
    except Exception as exc:
        raise AuditFailure("a JSON input could not be opened safely") from exc
    if not isinstance(payload, list):
        raise AuditFailure("the approved JSON record array must be at the root path")
    if not all(isinstance(record, Mapping) for record in payload):
        raise AuditFailure(
            "the approved JSON record array contains a non-object record"
        )
    records = [record for record in payload if isinstance(record, Mapping)]

    emotion_types: list[str | None] = []
    emotion_ids: list[str | None] = []
    situation_items: Counter[str] = Counter()
    situation_lengths = LengthStatistics()
    situation_null_count = 0
    talk_ids: Counter[str] = Counter()
    profile_ids: Counter[str] = Counter()
    talk_by_profile: dict[str, set[str]] = defaultdict(set)

    user_fields, user_parts = _field_presence_summary(
        records,
        USER_UTTERANCE_PATHS,
        require_strings=True,
    )
    system_fields, _ = _field_presence_summary(
        records,
        SYSTEM_RESPONSE_PATHS,
        require_strings=True,
    )
    joined_length_statistics = LengthStatistics()
    exact_texts: Counter[str] = Counter()
    normalized_texts: Counter[str] = Counter()
    normalized_text_labels: dict[str, set[tuple[str | None, str | None]]] = defaultdict(
        set
    )
    empty_text_count = 0

    for index, record in enumerate(records):
        _, raw_type = _get_path(record, TYPE_PATH)
        _, raw_emotion_id = _get_path(record, EMOTION_ID_PATH)
        emotion_type = _canonical_category(raw_type, "emotion.type")
        emotion_id = _canonical_category(raw_emotion_id, "emotion.emotion-id")
        emotion_types.append(emotion_type)
        emotion_ids.append(emotion_id)

        situation_exists, raw_situation = _get_path(record, SITUATION_PATH)
        if not situation_exists or raw_situation is None:
            situation_null_count += 1
        elif not isinstance(raw_situation, list):
            raise AuditFailure("the approved emotion.situation field is not an array")
        else:
            situation_lengths.counts[len(raw_situation)] += 1
            for item in raw_situation:
                category = _canonical_category(item, "emotion.situation")
                if category is not None:
                    situation_items[category] += 1

        _, raw_talk_id = _get_path(record, TALK_ID_PATH)
        _, raw_profile_id = _get_path(record, PROFILE_ID_PATH)
        talk_id = _canonical_category(raw_talk_id, "talk-id")
        profile_id = _canonical_category(raw_profile_id, "profile-id")
        if talk_id is not None:
            talk_ids[talk_id] += 1
        if profile_id is not None:
            profile_ids[profile_id] += 1
        if talk_id is not None and profile_id is not None:
            talk_by_profile[profile_id].add(talk_id)

        joined = _non_empty_join(user_parts[index])
        if not joined:
            empty_text_count += 1
            continue
        joined_length_statistics.add(joined)
        exact_texts[joined] += 1
        normalized = _normalize_text(joined)
        if normalized:
            normalized_texts[normalized] += 1
            normalized_text_labels[normalized].add((emotion_type, emotion_id))

    type_distribution, type_labels = _distribution(emotion_types)
    emotion_id_distribution, emotion_id_labels = _distribution(emotion_ids)
    situation_frequencies = dict(sorted(situation_items.items()))
    summary: dict[str, object] = {
        "logical_name": logical_name,
        "record_count": len(records),
        "emotion_type_distribution": type_distribution,
        "emotion_id_distribution": emotion_id_distribution,
        "situation_distribution": {
            "array_length_statistics": situation_lengths.summary(),
            "null_count": situation_null_count,
            "unique_item_count": len(situation_items),
            "item_frequencies": situation_frequencies,
        },
        "utterance_statistics": {
            "fields": user_fields,
            "joined_sample_count": sum(exact_texts.values()),
            "joined_text_length_statistics": joined_length_statistics.summary(),
            "empty_text_count": empty_text_count,
        },
        "system_response_statistics": {"fields": system_fields},
        "id_statistics": {
            "talk_id_unique_count": len(talk_ids),
            "profile_id_unique_count": len(profile_ids),
            "duplicate_talk_id_count": sum(
                max(0, count - 1) for count in talk_ids.values()
            ),
            "profile_talk_statistics": _profile_talk_statistics(talk_by_profile),
        },
    }
    return summary, SplitInternal(
        talk_ids=talk_ids,
        profile_ids=profile_ids,
        exact_texts=exact_texts,
        normalized_texts=normalized_texts,
        normalized_text_labels=dict(normalized_text_labels),
        type_labels=type_labels,
        emotion_id_labels=emotion_id_labels,
    )


def _overlap(
    train_values: Mapping[str, object], validation_values: Mapping[str, object]
) -> dict[str, int | float]:
    train_keys = set(train_values)
    validation_keys = set(validation_values)
    common = train_keys & validation_keys
    return {
        "overlap_count": len(common),
        "train_overlap_rate": round(len(common) / len(train_keys), 6)
        if train_keys
        else 0.0,
        "validation_overlap_rate": round(len(common) / len(validation_keys), 6)
        if validation_keys
        else 0.0,
    }


def _cross_split_leakage(
    train: SplitInternal, validation: SplitInternal
) -> dict[str, object]:
    normalized_common = set(train.normalized_texts) & set(validation.normalized_texts)
    conflict_count = sum(
        train.normalized_text_labels[text] != validation.normalized_text_labels[text]
        for text in normalized_common
    )
    return {
        "same_talk_id": _overlap(train.talk_ids, validation.talk_ids),
        "same_profile_id": _overlap(train.profile_ids, validation.profile_ids),
        "exact_user_text": _overlap(train.exact_texts, validation.exact_texts),
        "normalized_user_text": _overlap(
            train.normalized_texts, validation.normalized_texts
        ),
        "same_normalized_text_different_label_conflict_count": conflict_count,
        "emotion_type_class_set_difference": {
            "train_only": sorted(train.type_labels - validation.type_labels),
            "validation_only": sorted(validation.type_labels - train.type_labels),
        },
        "emotion_id_class_set_difference": {
            "train_only": sorted(
                train.emotion_id_labels - validation.emotion_id_labels
            ),
            "validation_only": sorted(
                validation.emotion_id_labels - train.emotion_id_labels
            ),
        },
    }


def audit_emotion_labels(
    *, train_json: Path, validation_json: Path
) -> dict[str, object]:
    train_summary, train = _inspect_split(train_json, "train_json")
    validation_summary, validation = _inspect_split(validation_json, "validation_json")
    leakage = _cross_split_leakage(train, validation)
    warnings: list[str] = [
        "official Training and Validation splits are preserved; this audit does not resplit records",
        "label options are structural candidates and are not automatically approved",
    ]
    if leakage["same_talk_id"]["overlap_count"]:  # type: ignore[index]
        warnings.append("talk-id overlap was detected across the official splits")
    if leakage["same_profile_id"]["overlap_count"]:  # type: ignore[index]
        warnings.append("profile-id overlap was detected across the official splits")
    if leakage["normalized_user_text"]["overlap_count"]:  # type: ignore[index]
        warnings.append(
            "normalized user-text overlap was detected across the official splits"
        )
    return {
        "audit_version": AUDIT_VERSION,
        "safe_output_policy": {
            "dialogue_text_serialized": False,
            "talk_or_profile_id_serialized": False,
            "unmatched_id_lists_serialized": False,
            "hashes_or_digests_serialized": False,
            "absolute_input_paths_serialized": False,
            "label_values_and_aggregate_counts_serialized": True,
        },
        "splits": {"train": train_summary, "validation": validation_summary},
        "cross_split_leakage": leakage,
        "recommended_label_options": [
            {
                "field": TYPE_PATH,
                "approved": False,
                "reason": "class distribution and split-specific class differences require human review",
            },
            {
                "field": EMOTION_ID_PATH,
                "approved": False,
                "reason": "class distribution and split-specific class differences require human review",
            },
        ],
        "decisions_required": [
            {
                "decision": "select_prediction_label",
                "status": "required",
                "candidates": [TYPE_PATH, EMOTION_ID_PATH],
            },
            {
                "decision": "approve_user_utterance_concatenation",
                "status": "required",
                "fields": list(USER_UTTERANCE_PATHS),
            },
            {
                "decision": "review_official_split_leakage",
                "status": "required",
                "checks": [
                    "talk_id",
                    "profile_id",
                    "exact_user_text",
                    "normalized_user_text",
                ],
            },
        ],
        "warnings": warnings,
        "limitations": [
            "source dialogue text and identifiers are retained only in process memory while counts are calculated",
            "exact and normalized text checks do not detect semantic or paraphrase duplicates",
            "label values are intentionally included as approved audit output categories",
        ],
    }


def _validate_paths(train_json: Path, validation_json: Path, output: Path) -> None:
    if not all(path.is_absolute() for path in (train_json, validation_json, output)):
        raise AuditFailure("all input and output paths must be absolute")
    if not train_json.is_file() or not validation_json.is_file():
        raise AuditFailure("a required JSON input file is unavailable")
    if (
        train_json.suffix.casefold() != ".json"
        or validation_json.suffix.casefold() != ".json"
    ):
        raise AuditFailure("both inputs must be JSON files")
    if not output.parent.is_dir():
        raise AuditFailure("the output directory is unavailable")
    if train_json.resolve() == validation_json.resolve():
        raise AuditFailure("Training and Validation inputs must be separate files")
    if output.resolve() in {train_json.resolve(), validation_json.resolve()}:
        raise AuditFailure("the output file must be separate from inputs")


def _write_output(path: Path, payload: Mapping[str, object]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".emotion-label-audit-",
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
            except Exception:
                pass
        raise AuditFailure(
            "the local audit report could not be written safely"
        ) from exc


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise AuditFailure("command arguments are invalid")


def _build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Audit approved emotional-dialogue JSON labels without exposing dialogue or IDs."
    )
    parser.add_argument("--train-json", required=True)
    parser.add_argument("--validation-json", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        arguments = parser.parse_args(argv)
        train_json = Path(arguments.train_json)
        validation_json = Path(arguments.validation_json)
        output = Path(arguments.output)
        _validate_paths(train_json, validation_json, output)
        _write_output(
            output,
            audit_emotion_labels(
                train_json=train_json, validation_json=validation_json
            ),
        )
    except AuditFailure as exc:
        print(f"Emotion label audit failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print(
            "Emotion label audit failed because of an unexpected local processing error",
            file=sys.stderr,
        )
        return 2
    print("Emotion label audit completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
