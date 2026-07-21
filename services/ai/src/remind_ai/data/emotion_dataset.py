"""Load only approved emotional-dialogue JSON fields into training samples."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


TURN_SEPARATOR = " [TURN] "
LABEL_PATH = ("profile", "emotion", "type")
TALK_ID_PATH = ("talk", "id", "talk-id")
PROFILE_ID_PATH = ("talk", "id", "profile-id")
USER_PATHS = (
    ("talk", "content", "HS01"),
    ("talk", "content", "HS02"),
    ("talk", "content", "HS03"),
)


class DatasetValidationError(ValueError):
    """Raised without including source values, IDs, or filesystem paths."""


@dataclass(frozen=True)
class EmotionSample:
    """One approved user-utterance sample with IDs kept outside model features."""

    text: str
    label: str
    sample_id: str
    group_id: str
    official_split: str


def normalize_text(value: str) -> str:
    """Normalize whitespace safely without exposing or persisting source text."""

    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value).strip())


def _path_value(record: Mapping[str, object], path: Sequence[str]) -> object | None:
    current: object = record
    for segment in path:
        if not isinstance(current, Mapping) or segment not in current:
            return None
        current = current[segment]
    return current


def _required_string(
    record: Mapping[str, object], path: Sequence[str], name: str
) -> str:
    value = _path_value(record, path)
    if not isinstance(value, str):
        raise DatasetValidationError(f"a required {name} field is unavailable")
    normalized = normalize_text(value)
    if not normalized:
        raise DatasetValidationError(f"a required {name} field is empty")
    return normalized


def sample_from_record(
    record: Mapping[str, object], official_split: str
) -> EmotionSample:
    """Build a sample from label, IDs, and HS01–HS03 only."""

    label = _required_string(record, LABEL_PATH, "emotion.type")
    sample_id = _required_string(record, TALK_ID_PATH, "talk-id")
    group_id = _required_string(record, PROFILE_ID_PATH, "profile-id")
    hs01 = _required_string(record, USER_PATHS[0], "HS01")
    hs02 = _required_string(record, USER_PATHS[1], "HS02")
    hs03_value = _path_value(record, USER_PATHS[2])
    if hs03_value is None:
        parts = [hs01, hs02]
    elif isinstance(hs03_value, str):
        hs03 = normalize_text(hs03_value)
        parts = [hs01, hs02, hs03] if hs03 else [hs01, hs02]
    else:
        raise DatasetValidationError("the optional HS03 field has an unsupported type")
    return EmotionSample(
        text=TURN_SEPARATOR.join(parts),
        label=label,
        sample_id=sample_id,
        group_id=group_id,
        official_split=official_split,
    )


def load_json_samples(path: Path, official_split: str) -> list[EmotionSample]:
    """Load an approved root record array without returning raw records."""

    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(
            "a JSON input could not be decoded safely"
        ) from exc
    except Exception as exc:
        raise DatasetValidationError("a JSON input could not be opened safely") from exc
    if not isinstance(payload, list):
        raise DatasetValidationError(
            "the approved JSON record array must be at the root"
        )
    samples: list[EmotionSample] = []
    for record in payload:
        if not isinstance(record, Mapping):
            raise DatasetValidationError(
                "the JSON record array contains a non-object record"
            )
        samples.append(sample_from_record(record, official_split))
    return samples


def load_dataset(train_json: Path, validation_json: Path) -> list[EmotionSample]:
    """Combine official files internally while retaining their provenance only."""

    samples = [
        *load_json_samples(train_json, "official_train"),
        *load_json_samples(validation_json, "official_validation"),
    ]
    if not samples:
        raise DatasetValidationError("the combined approved dataset is empty")
    if len({sample.label for sample in samples}) < 2:
        raise DatasetValidationError("at least two emotion.type classes are required")
    return samples
