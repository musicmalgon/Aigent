"""Privacy-preserving local structure audit for emotional-dialogue files.

The command inspects only paths explicitly supplied by its caller. It reports
schema and aggregate quality signals without serializing source text, record
identifiers, group values, row-level results, or comparison digests.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import re
import sys
import tempfile
import warnings as python_warnings
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, NoReturn, TypeGuard


AUDIT_VERSION = "local-structure-audit-v1"
DATASET_DISPLAY_NAME = "emotional-dialogue"
MAX_JSON_DISCOVERY_DEPTH = 8
MAX_VISIBLE_LABEL_VALUES = 50
MAX_VISIBLE_LABEL_LENGTH = 64

ID_FIELD_TOKENS = (
    "id",
    "identifier",
    "key",
    "uuid",
    "아이디",
    "식별",
)
GROUP_FIELD_TOKENS = (
    "group",
    "conversation",
    "dialog",
    "session",
    "speaker",
    "author",
    "user",
    "document",
    "그룹",
    "대화",
    "화자",
    "사용자",
    "문서",
)
TEXT_FIELD_TOKENS = (
    "text",
    "sentence",
    "utterance",
    "dialogue",
    "dialog",
    "content",
    "transcript",
    "원문",
    "문장",
    "발화",
    "대화",
    "내용",
)
LABEL_FIELD_TOKENS = (
    "label",
    "emotion",
    "category",
    "class",
    "target",
    "라벨",
    "감정",
    "분류",
    "범주",
)
STRUCTURAL_JSON_KEYS = frozenset(
    {
        "annotation",
        "annotations",
        "data",
        "document",
        "documents",
        "file",
        "files",
        "item",
        "items",
        "label",
        "labels",
        "metadata",
        "record",
        "records",
        "result",
        "results",
        "source",
    }
)
GENERIC_HEADER_KEYS = frozenset(
    {
        "age",
        "count",
        "created_at",
        "date",
        "index",
        "length",
        "number",
        "score",
        "sequence",
        "status",
        "time",
        "timestamp",
        "turn",
        "type",
        "updated_at",
        "value",
    }
)
LABEL_VALUE_MARKERS = frozenset(
    {
        "category",
        "class",
        "code",
        "emotion",
        "label",
        "target",
        "감정",
        "라벨",
        "범주",
        "분류",
    }
)

PRIVACY_PATTERNS: dict[str, re.Pattern[str]] = {
    "email_like": re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"),
    "phone_like": re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)"),
}


class AuditFailure(RuntimeError):
    """A caller-safe audit error whose message never contains an input path."""


@dataclass
class InternalRecords:
    """Digest-only record information retained for joining and leakage checks."""

    record_count: int
    field_names: list[str]
    field_value_digests: dict[str, Counter[str]]
    missing_by_field: dict[str, int]
    row_digests: Counter[str]
    id_candidates: list[str]
    group_candidates: list[str]
    text_candidates: list[str]
    statistics_available: bool = True
    label_candidates: list[str] = field(default_factory=list)
    privacy_counts: Counter[str] = field(default_factory=Counter)

    def values_for(self, field_name: str | None) -> Counter[str]:
        if field_name is None:
            return Counter()
        return self.field_value_digests.get(field_name, Counter())

    def missing_for(self, field_name: str | None) -> int:
        if field_name is None:
            return self.record_count
        return self.missing_by_field.get(field_name, self.record_count)


@dataclass
class SourceAudit:
    summary: dict[str, Any]
    records: InternalRecords
    warnings: list[str]
    limitations: list[str]


@dataclass
class LabelAudit:
    summary: dict[str, Any]
    records: InternalRecords
    selected_label_field: str | None
    label_distribution: dict[str, int]
    warnings: list[str]
    limitations: list[str]


@dataclass(frozen=True)
class AuditOptions:
    source_id_field: str | None
    label_id_field: str | None
    text_field: str | None
    label_field: str | None
    group_field: str | None
    source_sheet: str | None
    encoding: str


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _field_name_key(value: str) -> str:
    return re.sub(r"[\s_.-]+", "_", value.strip().casefold())


def _contains_token(field_name: str, tokens: Sequence[str]) -> bool:
    normalized = _field_name_key(field_name)
    parts = set(normalized.split("_"))
    for token in tokens:
        if token in parts:
            return True
        if not token.isascii() or len(token) >= 4:
            if token in normalized:
                return True
    return False


def _id_candidates(field_names: Iterable[str]) -> list[str]:
    return sorted(
        field_name
        for field_name in field_names
        if _contains_token(field_name, ID_FIELD_TOKENS)
    )


def _group_candidates(field_names: Iterable[str]) -> list[str]:
    return sorted(
        field_name
        for field_name in field_names
        if _contains_token(field_name, GROUP_FIELD_TOKENS)
    )


def _text_candidates(field_names: Iterable[str]) -> list[str]:
    return sorted(
        field_name
        for field_name in field_names
        if _contains_token(field_name, TEXT_FIELD_TOKENS)
    )


def _label_candidates(field_names: Iterable[str]) -> list[str]:
    return sorted(
        field_name
        for field_name in field_names
        if _contains_token(field_name, LABEL_FIELD_TOKENS)
    )


def _type_name(value: object) -> str:
    if _is_missing(value):
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, time):
        return "time"
    if isinstance(value, timedelta):
        return "duration"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "array"
    return "other"


def _canonical_value(value: object) -> object:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, float):
        if math.isnan(value):
            return "number:nan"
        if math.isinf(value):
            return (
                "number:positive-infinity" if value > 0 else "number:negative-infinity"
            )
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(nested)
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return f"type:{type(value).__name__}"


def _digest(value: object) -> str:
    encoded = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _privacy_counts_for_value(value: object) -> Counter[str]:
    counts: Counter[str] = Counter()
    if isinstance(value, str):
        for name, pattern in PRIVACY_PATTERNS.items():
            counts[name] += len(pattern.findall(value))
    elif isinstance(value, Mapping):
        for nested in value.values():
            counts.update(_privacy_counts_for_value(nested))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            counts.update(_privacy_counts_for_value(nested))
    return counts


def _is_safe_field_name(value: object) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > 128:
        return False
    if any(character in candidate for character in "\r\n\t"):
        return False
    if len(candidate.split()) > 5:
        return False
    if any(pattern.search(candidate) for pattern in PRIVACY_PATTERNS.values()):
        return False
    return True


def _looks_like_schema_header_field(field_name: str) -> bool:
    normalized = _field_name_key(field_name)
    if normalized in GENERIC_HEADER_KEYS:
        return True
    semantic_tokens = (
        *ID_FIELD_TOKENS,
        *GROUP_FIELD_TOKENS,
        *TEXT_FIELD_TOKENS,
        *LABEL_FIELD_TOKENS,
    )
    if normalized in {token for token in semantic_tokens if token.isascii()}:
        return True
    schema_pattern = re.compile(
        r"(?:(?:source|label|record|alternate|group|conversation|dialog|session|"
        r"speaker|author|user|document|file|annotation|sample|item|emotion|"
        r"category|class|target|embedded|original|raw|diary)_)*"
        r"(?:id|identifier|key|uuid|text|sentence|utterance|dialogue|dialog|"
        r"content|transcript|label|emotion|category|class|target)"
    )
    if normalized.isascii():
        return schema_pattern.fullmatch(normalized) is not None
    non_ascii_tokens = tuple(token for token in semantic_tokens if not token.isascii())
    return (
        len(normalized) <= 30
        and not any(character.isdigit() for character in normalized)
        and _contains_token(normalized, non_ascii_tokens)
    )


def _safe_header(
    values: Sequence[object],
    *,
    trusted_field_names: Iterable[str] = (),
) -> list[str] | None:
    candidates = [
        value.strip() if isinstance(value, str) else value for value in values
    ]
    if not candidates or not all(_is_safe_field_name(value) for value in candidates):
        return None
    header = [str(value) for value in candidates]
    if len(set(header)) != len(header):
        return None
    trusted = set(trusted_field_names)
    safe_candidates: list[str] = []
    recognized_count = 0
    for index, field_name in enumerate(header, start=1):
        recognized = bool(
            re.fullmatch(
                r"[^\W\d]\w*(?:\.[^\W\d]\w*)*",
                field_name,
                re.UNICODE,
            )
            and (_looks_like_schema_header_field(field_name) or field_name in trusted)
        )
        if recognized:
            safe_candidates.append(field_name)
            recognized_count += 1
        else:
            safe_candidates.append(f"column_{index}")
    if recognized_count == 0:
        return None
    return safe_candidates


def _safe_structural_key(value: object) -> bool:
    if not _is_safe_field_name(value):
        return False
    candidate = str(value)
    return len(candidate) <= 80 and not any(
        character in candidate for character in "/\\:"
    )


def _known_structural_key(value: object) -> bool:
    if not _safe_structural_key(value):
        return False
    return _field_name_key(str(value)) in STRUCTURAL_JSON_KEYS


def _length_at_rank(length_counts: Counter[int], rank: int) -> int:
    seen = 0
    for length, count in sorted(length_counts.items()):
        seen += count
        if seen > rank:
            return length
    raise ValueError("length rank is outside the observed range")


def _length_summary(
    length_counts: Counter[int],
) -> dict[str, int | float | None]:
    count = sum(length_counts.values())
    if count == 0:
        return {
            "count": 0,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "median": None,
            "p95": None,
        }
    middle = count // 2
    if count % 2:
        median = float(_length_at_rank(length_counts, middle))
    else:
        median = (
            _length_at_rank(length_counts, middle - 1)
            + _length_at_rank(length_counts, middle)
        ) / 2
    p95_rank = max(0, math.ceil(0.95 * count) - 1)
    return {
        "count": count,
        "minimum": min(length_counts),
        "maximum": max(length_counts),
        "mean": round(
            sum(length * frequency for length, frequency in length_counts.items())
            / count,
            3,
        ),
        "median": median,
        "p95": float(_length_at_rank(length_counts, p95_rank)),
    }


def _record_internals(
    records: Iterable[Mapping[str, object]],
    field_names: Sequence[str],
    *,
    additional_text_fields: Iterable[str] = (),
    digest_fields: Iterable[str] | None = None,
) -> tuple[
    InternalRecords,
    dict[str, dict[str, int]],
    dict[str, dict[str, int | float | None]],
]:
    ordered_fields = list(dict.fromkeys(field_names))
    selected_digest_fields = (
        set(ordered_fields) if digest_fields is None else set(digest_fields)
    )
    value_digests: dict[str, Counter[str]] = {
        field_name: Counter()
        for field_name in ordered_fields
        if field_name in selected_digest_fields
    }
    missing_counts = {field_name: 0 for field_name in ordered_fields}
    type_counts: dict[str, Counter[str]] = {
        field_name: Counter() for field_name in ordered_fields
    }
    row_digests: Counter[str] = Counter()
    privacy_counts: Counter[str] = Counter()
    text_fields = list(
        dict.fromkeys(
            [
                *_text_candidates(ordered_fields),
                *(
                    field_name
                    for field_name in additional_text_fields
                    if field_name in ordered_fields
                ),
            ]
        )
    )
    text_lengths: dict[str, Counter[int]] = {
        field_name: Counter() for field_name in text_fields
    }
    record_count = 0
    ordered_field_set = set(ordered_fields)

    for record in records:
        record_count += 1
        for field_name in ordered_fields:
            value = record.get(field_name)
            type_counts[field_name][_type_name(value)] += 1
            if _is_missing(value):
                missing_counts[field_name] += 1
            else:
                if field_name in value_digests:
                    value_digests[field_name][_digest(value)] += 1
                if field_name in text_lengths and isinstance(value, str):
                    text_lengths[field_name][len(value)] += 1
            privacy_counts.update(_privacy_counts_for_value(value))
        for key, value in record.items():
            if str(key) not in ordered_field_set:
                privacy_counts.update(_privacy_counts_for_value(value))
        row_digests[_digest(record)] += 1

    internals = InternalRecords(
        record_count=record_count,
        field_names=ordered_fields,
        field_value_digests=value_digests,
        missing_by_field=missing_counts,
        row_digests=row_digests,
        id_candidates=_id_candidates(ordered_fields),
        group_candidates=_group_candidates(ordered_fields),
        text_candidates=text_fields,
        label_candidates=_label_candidates(ordered_fields),
        privacy_counts=privacy_counts,
    )
    serialized_types = {
        field_name: dict(sorted(counter.items()))
        for field_name, counter in type_counts.items()
    }
    serialized_lengths = {
        field_name: _length_summary(lengths)
        for field_name, lengths in text_lengths.items()
    }
    return internals, serialized_types, serialized_lengths


def _load_openpyxl() -> Any:
    try:
        return importlib.import_module("openpyxl")
    except ImportError as exc:
        raise AuditFailure(
            "XLSX support is unavailable; install the declared local audit dependency"
        ) from exc


def _audit_xlsx(
    path: Path,
    *,
    source_sheet: str | None,
    explicit_id_field: str | None,
    explicit_text_field: str | None,
    explicit_group_field: str | None,
) -> SourceAudit:
    openpyxl = _load_openpyxl()
    captured_library_warnings: list[python_warnings.WarningMessage] = []
    try:
        with python_warnings.catch_warnings(record=True) as captured_library_warnings:
            python_warnings.simplefilter("always")
            workbook = openpyxl.load_workbook(
                path,
                read_only=True,
                data_only=True,
                keep_links=False,
                keep_vba=False,
            )
    except Exception as exc:
        raise AuditFailure("an XLSX source file could not be opened safely") from exc

    audit_warnings: list[str] = []
    limitations: list[str] = []
    try:
        sheet_summaries = [
            {
                "name": worksheet.title,
                "state": worksheet.sheet_state,
                "reported_row_count": int(worksheet.max_row or 0),
                "reported_column_count": int(worksheet.max_column or 0),
            }
            for worksheet in workbook.worksheets
        ]
        hidden_sheets = [
            worksheet.title
            for worksheet in workbook.worksheets
            if worksheet.sheet_state != "visible"
        ]
        for sheet_name in hidden_sheets:
            audit_warnings.append(
                f"worksheet {sheet_name!r} is hidden; its cells were not inspected"
            )

        if source_sheet is not None:
            if source_sheet not in workbook.sheetnames:
                raise AuditFailure("the requested worksheet is not present")
            selected = workbook[source_sheet]
            if selected.sheet_state != "visible":
                raise AuditFailure("the requested worksheet is not visible")
        else:
            selected = next(
                (
                    worksheet
                    for worksheet in workbook.worksheets
                    if worksheet.sheet_state == "visible"
                ),
                None,
            )
            if selected is None:
                raise AuditFailure("the workbook has no visible worksheet")

        with python_warnings.catch_warnings(record=True) as row_setup_warnings:
            python_warnings.simplefilter("always")
            row_iterator = selected.iter_rows(values_only=True)
            try:
                first_row = tuple(next(row_iterator))
            except StopIteration:
                first_row = ()
        captured_library_warnings.extend(row_setup_warnings)

        header = _safe_header(
            first_row,
            trusted_field_names=(
                field_name
                for field_name in (
                    explicit_id_field,
                    explicit_text_field,
                    explicit_group_field,
                )
                if field_name is not None
            ),
        )
        header_detected = header is not None
        header_values_redacted = False
        if header is None:
            header = [f"column_{index}" for index in range(1, len(first_row) + 1)]
            audit_warnings.append(
                "a safe header row could not be confirmed; generated column names were used"
            )
        else:
            header_values_redacted = any(
                field_name
                != (
                    first_row[index].strip()
                    if isinstance(first_row[index], str)
                    else first_row[index]
                )
                for index, field_name in enumerate(header)
            )
            if header_values_redacted:
                audit_warnings.append(
                    "unconfirmed header values were replaced with generated column names"
                )

        maximum_width = max(
            len(header),
            len(first_row),
            int(selected.max_column or 0),
        )
        if maximum_width > len(header):
            header.extend(
                f"column_{index}" for index in range(len(header) + 1, maximum_width + 1)
            )
            audit_warnings.append(
                "some rows exceeded the header width; generated column names were used"
            )

        stream_state = {"rows_exceeding_header": 0}

        def record_stream() -> Iterable[Mapping[str, object]]:
            def as_record(values: tuple[object, ...]) -> Mapping[str, object]:
                if len(values) > len(header):
                    stream_state["rows_exceeding_header"] += 1
                return {
                    field_name: values[index] if index < len(values) else None
                    for index, field_name in enumerate(header)
                }

            if (
                first_row
                and not header_detected
                and any(not _is_missing(value) for value in first_row)
            ):
                yield as_record(first_row)
            for row in row_iterator:
                values = tuple(row)
                if any(not _is_missing(value) for value in values):
                    yield as_record(values)

        digest_fields = {
            *_id_candidates(header),
            *_group_candidates(header),
            *_text_candidates(header),
            *(
                field_name
                for field_name in (
                    explicit_id_field,
                    explicit_text_field,
                    explicit_group_field,
                )
                if field_name is not None
            ),
        }
        with python_warnings.catch_warnings(record=True) as row_read_warnings:
            python_warnings.simplefilter("always")
            internals, type_counts, text_lengths = _record_internals(
                record_stream(),
                header,
                additional_text_fields=(
                    [explicit_text_field] if explicit_text_field is not None else []
                ),
                digest_fields=digest_fields,
            )
        captured_library_warnings.extend(row_read_warnings)
        if explicit_id_field is not None and explicit_id_field in header:
            internals.id_candidates = sorted(
                {*internals.id_candidates, explicit_id_field}
            )
        if explicit_group_field is not None and explicit_group_field in header:
            internals.group_candidates = sorted(
                {*internals.group_candidates, explicit_group_field}
            )
        if explicit_text_field is not None and explicit_text_field in header:
            internals.text_candidates = sorted(
                {*internals.text_candidates, explicit_text_field}
            )
        if stream_state["rows_exceeding_header"]:
            audit_warnings.append(
                "some rows exceeded the reported worksheet width; extra cells were not "
                "included in field-level summaries"
            )

        summary: dict[str, Any] = {
            "sheet_count": len(sheet_summaries),
            "sheets": sheet_summaries,
            "selected_sheet": selected.title,
            "row_count": internals.record_count,
            "column_count": len(header),
            "header_detected": header_detected,
            "header_values_redacted": header_values_redacted,
            "header_candidates": header,
            "missing_by_field": dict(sorted(internals.missing_by_field.items())),
            "type_counts_by_field": type_counts,
            "duplicate_row_count": sum(
                max(0, count - 1) for count in internals.row_digests.values()
            ),
            "text_length_statistics": text_lengths,
            "candidate_id_fields": internals.id_candidates,
            "candidate_group_fields": internals.group_candidates,
        }
        if captured_library_warnings:
            audit_warnings.append(
                "the XLSX library emitted warnings; review workbook compatibility locally"
            )
        if not header_detected:
            limitations.append(
                "field-level interpretation is provisional because no safe header was confirmed"
            )
        return SourceAudit(summary, internals, audit_warnings, limitations)
    except AuditFailure:
        raise
    except Exception as exc:
        raise AuditFailure("an XLSX source file could not be audited safely") from exc
    finally:
        try:
            workbook.close()
        except Exception:
            pass


def _safe_path_segment(key: object) -> str:
    return str(key) if _known_structural_key(key) else "*"


def _is_record_array(
    value: object,
) -> TypeGuard[list[Mapping[str, object]]]:
    return isinstance(value, list) and (
        not value or all(isinstance(item, Mapping) for item in value)
    )


def _mapping_has_scalar_field(value: Mapping[object, object]) -> bool:
    return any(not isinstance(item, (Mapping, list)) for item in value.values())


def _discover_json_candidates(
    value: object,
    *,
    path: str = "$",
    depth: int = 0,
) -> list[tuple[str, list[Mapping[str, object]]]]:
    if depth > MAX_JSON_DISCOVERY_DEPTH:
        return []

    candidates: list[tuple[str, list[Mapping[str, object]]]] = []
    if _is_record_array(value):
        candidates.append((path, list(value)))

    if isinstance(value, Mapping):
        if path.rsplit(".", maxsplit=1)[-1] in {"annotation", "annotations"}:
            candidates.append((path, [value]))
        mapping_values = list(value.values())
        if (
            value
            and all(isinstance(item, Mapping) for item in mapping_values)
            and not all(_known_structural_key(key) for key in value)
            and all(
                _mapping_has_scalar_field(item)
                for item in mapping_values
                if isinstance(item, Mapping)
            )
        ):
            candidates.append(
                (
                    f"{path}.*",
                    [item for item in mapping_values if isinstance(item, Mapping)],
                )
            )
        for key, nested in value.items():
            nested_path = f"{path}.{_safe_path_segment(key)}"
            if isinstance(nested, (Mapping, list)):
                candidates.extend(
                    _discover_json_candidates(
                        nested,
                        path=nested_path,
                        depth=depth + 1,
                    )
                )
    elif isinstance(value, list):
        for nested in value:
            if isinstance(nested, (Mapping, list)):
                candidates.extend(
                    _discover_json_candidates(
                        nested,
                        path=f"{path}[*]",
                        depth=depth + 1,
                    )
                )

    return candidates


def _candidate_field_names(
    records: Sequence[Mapping[str, object]],
    *,
    trusted_fields: Iterable[str] = (),
) -> list[str]:
    trusted = set(trusted_fields)
    names: set[str] = set()
    for record in records:
        for key in record:
            if _is_safe_field_name(key) and (
                str(key) in trusted
                or _looks_like_schema_header_field(str(key))
                or _known_structural_key(key)
            ):
                names.add(str(key))
    return sorted(names)


def _record_field_names_were_redacted(
    records: Sequence[Mapping[str, object]],
    visible_field_names: Sequence[str],
) -> bool:
    visible = set(visible_field_names)
    return any(str(key) not in visible for record in records for key in record)


def _choose_json_records(
    candidates: Sequence[tuple[str, list[Mapping[str, object]]]],
    *,
    required_fields: Sequence[str],
) -> tuple[str | None, list[Mapping[str, object]], bool]:
    if not candidates:
        return None, [], False

    required = {field_name for field_name in required_fields if field_name}
    if required:
        matching = [
            candidate
            for candidate in candidates
            if required.issubset(
                set(
                    _candidate_field_names(
                        candidate[1],
                        trusted_fields=required,
                    )
                )
            )
        ]
        if len(matching) == 1:
            return matching[0][0], matching[0][1], False
        if len(matching) > 1:
            return None, [], True

    root = [candidate for candidate in candidates if candidate[0] == "$"]
    if len(root) == 1:
        return root[0][0], root[0][1], False

    preferred = [
        candidate for candidate in candidates if candidate[0] in {"$.records", "$.data"}
    ]
    if len(preferred) == 1:
        return preferred[0][0], preferred[0][1], False

    if len(candidates) == 1:
        return candidates[0][0], candidates[0][1], False
    return None, [], True


def _categorical_label_distribution(
    records: Sequence[Mapping[str, object]],
    label_field: str | None,
    *,
    label_field_was_explicit: bool,
) -> tuple[dict[str, int], bool, int, int]:
    if label_field is None:
        return {}, True, 0, len(records)

    values: list[object] = []
    missing_count = 0
    for record in records:
        value = record.get(label_field)
        if _is_missing(value):
            missing_count += 1
        else:
            values.append(value)

    canonical_values = [_canonical_value(value) for value in values]
    distinct_serialized = {
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for value in canonical_values
    }
    distinct_count = len(distinct_serialized)
    categorical_string = re.compile(r"[\w.+:-]+", re.UNICODE)
    label_field_is_semantic = (
        label_field is not None and label_field in _label_candidates([label_field])
    )

    def safe_categorical_value(value: object) -> bool:
        if isinstance(value, (bool, int)):
            return True
        if isinstance(value, float):
            return math.isfinite(value)
        if not isinstance(value, str):
            return False
        stripped = value.strip()
        if (
            len(stripped) > MAX_VISIBLE_LABEL_LENGTH
            or categorical_string.fullmatch(stripped) is None
            or any(pattern.search(stripped) for pattern in PRIVACY_PATTERNS.values())
        ):
            return False
        tokens = {
            token for token in re.split(r"[_.+:-]+", stripped.casefold()) if token
        }
        return not tokens.isdisjoint(LABEL_VALUE_MARKERS)

    safe = (
        label_field_was_explicit
        and label_field_is_semantic
        and bool(values)
        and distinct_count < len(values)
        and distinct_count <= MAX_VISIBLE_LABEL_VALUES
        and all(safe_categorical_value(value) for value in values)
    )
    if not safe:
        return {}, True, distinct_count, missing_count

    distribution: Counter[str] = Counter()
    for value in values:
        distribution[str(value)] += 1
    return dict(sorted(distribution.items())), False, distinct_count, missing_count


def _audit_json(
    path: Path,
    *,
    encoding: str,
    explicit_label_id_field: str | None,
    explicit_label_field: str | None,
    explicit_text_field: str | None,
    explicit_group_field: str | None,
) -> LabelAudit:
    try:
        with path.open("r", encoding=encoding) as json_file:
            payload = json.load(json_file)
    except (LookupError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditFailure("a label JSON file could not be decoded safely") from exc
    except Exception as exc:
        raise AuditFailure("a label JSON file could not be opened safely") from exc

    audit_warnings: list[str] = []
    limitations: list[str] = []
    top_level_type = (
        "array"
        if isinstance(payload, list)
        else "object"
        if isinstance(payload, Mapping)
        else type(payload).__name__
    )

    top_level_keys: list[str] = []
    top_level_keys_redacted = False
    if isinstance(payload, Mapping):
        raw_keys = list(payload.keys())
        if len(raw_keys) <= 50 and all(_known_structural_key(key) for key in raw_keys):
            top_level_keys = sorted(str(key) for key in raw_keys)
        elif raw_keys:
            top_level_keys_redacted = True
            audit_warnings.append(
                "unknown top-level JSON keys were redacted because they may be record "
                "identifiers"
            )

    candidates = _discover_json_candidates(payload)
    required_fields = [
        field_name
        for field_name in (
            explicit_label_id_field,
            explicit_label_field,
        )
        if field_name is not None
    ]
    selected_path, selected_records, ambiguous = _choose_json_records(
        candidates,
        required_fields=required_fields,
    )
    if ambiguous:
        audit_warnings.append(
            "multiple JSON record-array candidates were found; no structure was auto-selected"
        )
        limitations.append(
            "record-level label statistics require a human-confirmed JSON structure"
        )
    elif selected_path is None:
        audit_warnings.append("no unambiguous JSON record-array candidate was found")
        limitations.append(
            "record-level label statistics are unavailable for this JSON structure"
        )

    trusted_fields = [
        field_name
        for field_name in (
            explicit_label_id_field,
            explicit_label_field,
            explicit_text_field,
            explicit_group_field,
        )
        if field_name is not None
    ]
    field_names = _candidate_field_names(
        selected_records,
        trusted_fields=trusted_fields,
    )
    field_names_redacted = _record_field_names_were_redacted(
        selected_records,
        field_names,
    )
    if field_names_redacted:
        audit_warnings.append(
            "unconfirmed record field names were redacted because they may be identifiers"
        )
    internals, type_counts, text_lengths = _record_internals(
        selected_records,
        field_names,
    )
    internals.statistics_available = selected_path is not None
    if explicit_label_id_field is not None and explicit_label_id_field in field_names:
        internals.id_candidates = sorted(
            {*internals.id_candidates, explicit_label_id_field}
        )
    if explicit_group_field is not None and explicit_group_field in field_names:
        internals.group_candidates = sorted(
            {*internals.group_candidates, explicit_group_field}
        )
    if explicit_text_field is not None and explicit_text_field in field_names:
        internals.text_candidates = sorted(
            {*internals.text_candidates, explicit_text_field}
        )
    if explicit_label_field is not None and explicit_label_field in field_names:
        internals.label_candidates = sorted(
            {*internals.label_candidates, explicit_label_field}
        )
    label_candidates = internals.label_candidates
    if explicit_label_field is not None:
        selected_label_field = (
            explicit_label_field if explicit_label_field in field_names else None
        )
        if selected_label_field is None:
            audit_warnings.append(
                "the requested label field was not found in the selected JSON records"
            )
    elif len(label_candidates) == 1:
        selected_label_field = label_candidates[0]
    else:
        selected_label_field = None
        if len(label_candidates) > 1:
            audit_warnings.append(
                "multiple label field candidates were found; no label field was auto-selected"
            )

    distribution, values_redacted, distinct_count, missing_label_count = (
        _categorical_label_distribution(
            selected_records,
            selected_label_field,
            label_field_was_explicit=(
                explicit_label_field is not None
                and selected_label_field == explicit_label_field
            ),
        )
    )
    if selected_label_field is not None and values_redacted:
        audit_warnings.append(
            "label values were redacted; a person must verify whether the field is categorical"
        )

    text_field_present = bool(internals.text_candidates)
    if explicit_text_field is not None and explicit_text_field in field_names:
        text_field_present = True

    duplicate_id_count = 0
    selected_id_field: str | None = None
    if explicit_label_id_field is not None and explicit_label_id_field in field_names:
        selected_id_field = explicit_label_id_field
    elif len(internals.id_candidates) == 1:
        selected_id_field = internals.id_candidates[0]
    if selected_id_field is not None:
        duplicate_id_count = sum(
            max(0, count - 1)
            for count in internals.values_for(selected_id_field).values()
        )

    statistics_available = internals.statistics_available
    label_statistics_available = (
        statistics_available and selected_label_field is not None
    )
    summary: dict[str, Any] = {
        "top_level_type": top_level_type,
        "top_level_keys": top_level_keys,
        "top_level_keys_redacted": top_level_keys_redacted,
        "record_array_candidate_paths": sorted({path for path, _ in candidates}),
        "selected_record_array_path": selected_path,
        "statistics_available": statistics_available,
        "label_statistics_available": label_statistics_available,
        "record_count": internals.record_count if statistics_available else None,
        "field_name_candidates": field_names,
        "field_names_redacted": field_names_redacted,
        "candidate_id_fields": internals.id_candidates,
        "candidate_label_fields": label_candidates,
        "candidate_group_fields": internals.group_candidates,
        "text_field_present": text_field_present if statistics_available else None,
        "missing_by_field": dict(sorted(internals.missing_by_field.items())),
        "type_counts_by_field": type_counts,
        "text_length_statistics": text_lengths,
        "duplicate_record_count": (
            sum(max(0, count - 1) for count in internals.row_digests.values())
            if statistics_available
            else None
        ),
        "duplicate_id_count": duplicate_id_count if statistics_available else None,
        "selected_label_field": selected_label_field,
        "label_values_redacted": values_redacted,
        "distinct_label_count": (
            distinct_count if label_statistics_available else None
        ),
        "missing_label_count": (
            missing_label_count if label_statistics_available else None
        ),
    }
    return LabelAudit(
        summary=summary,
        records=internals,
        selected_label_field=selected_label_field,
        label_distribution=distribution,
        warnings=audit_warnings,
        limitations=limitations,
    )


def _duplicate_count(counter: Counter[str]) -> int:
    return sum(max(0, count - 1) for count in counter.values())


def _pair_records(
    source: InternalRecords,
    labels: InternalRecords,
    *,
    source_field: str | None,
    label_field: str | None,
    strategy: str,
) -> dict[str, Any]:
    base = {
        "source_record_count": (
            source.record_count if source.statistics_available else None
        ),
        "label_record_count": (
            labels.record_count if labels.statistics_available else None
        ),
        "matched_record_count": None,
        "source_only_count": None,
        "label_only_count": None,
        "duplicate_source_key_count": None,
        "duplicate_label_key_count": None,
        "ambiguous_match_count": None,
        "candidate_source_id_fields": source.id_candidates,
        "candidate_label_id_fields": labels.id_candidates,
        "selected_join_strategy": strategy,
        "join_status": "unresolved",
    }
    if not source.statistics_available or not labels.statistics_available:
        return base
    if strategy == "unresolved" or source_field is None or label_field is None:
        return base
    if source_field not in source.field_names or label_field not in labels.field_names:
        base["join_status"] = "invalid"
        return base

    source_keys = source.values_for(source_field)
    label_keys = labels.values_for(label_field)
    source_missing = source.missing_for(source_field)
    label_missing = labels.missing_for(label_field)
    duplicate_source = _duplicate_count(source_keys)
    duplicate_label = _duplicate_count(label_keys)
    shared = set(source_keys) & set(label_keys)
    ambiguous = {key for key in shared if source_keys[key] != 1 or label_keys[key] != 1}
    matched = sum(1 for key in shared if source_keys[key] == 1 and label_keys[key] == 1)
    source_only = source_missing + sum(
        count for key, count in source_keys.items() if key not in label_keys
    )
    label_only = label_missing + sum(
        count for key, count in label_keys.items() if key not in source_keys
    )

    base.update(
        {
            "matched_record_count": matched,
            "source_only_count": source_only,
            "label_only_count": label_only,
            "duplicate_source_key_count": duplicate_source,
            "duplicate_label_key_count": duplicate_label,
            "ambiguous_match_count": len(ambiguous),
        }
    )
    if duplicate_source or duplicate_label or source_missing or label_missing:
        base["join_status"] = "invalid"
    elif source_only or label_only:
        base["join_status"] = "partial"
    elif matched == source.record_count and matched == labels.record_count:
        base["join_status"] = "complete"
    else:
        base["join_status"] = "partial"
    return base


def _intersection_count(
    left: Counter[str],
    right: Counter[str],
) -> int:
    return sum(min(left[key], right[key]) for key in set(left) & set(right))


def _selected_or_unique(
    explicit: str | None,
    candidates: Sequence[str],
) -> str | None:
    if explicit is not None:
        return explicit
    if len(candidates) == 1:
        return candidates[0]
    return None


def _cross_split_leakage(
    train_source: InternalRecords,
    train_labels: InternalRecords,
    validation_source: InternalRecords,
    validation_labels: InternalRecords,
    *,
    source_id_field: str | None,
    label_id_field: str | None,
    text_field: str | None,
    group_field: str | None,
) -> dict[str, int | None]:
    selected_source_id = _selected_or_unique(
        source_id_field,
        train_source.id_candidates,
    )
    if (
        selected_source_id is None
        or selected_source_id not in train_source.field_names
        or selected_source_id not in validation_source.field_names
    ):
        same_source_ids: int | None = None
    else:
        same_source_ids = _intersection_count(
            train_source.values_for(selected_source_id),
            validation_source.values_for(selected_source_id),
        )

    selected_group = _selected_or_unique(
        group_field,
        train_source.group_candidates,
    )
    if (
        selected_group is None
        or selected_group not in train_source.field_names
        or selected_group not in validation_source.field_names
    ):
        same_groups: int | None = None
    else:
        same_groups = _intersection_count(
            train_source.values_for(selected_group),
            validation_source.values_for(selected_group),
        )

    selected_text = _selected_or_unique(
        text_field,
        train_source.text_candidates,
    )
    if (
        selected_text is None
        or selected_text not in train_source.field_names
        or selected_text not in validation_source.field_names
    ):
        same_texts: int | None = None
    else:
        same_texts = _intersection_count(
            train_source.values_for(selected_text),
            validation_source.values_for(selected_text),
        )

    selected_label_id = _selected_or_unique(
        label_id_field,
        train_labels.id_candidates,
    )
    wrong_train_to_validation: int | None = None
    wrong_validation_to_train: int | None = None
    if (
        selected_source_id is not None
        and selected_label_id is not None
        and train_source.statistics_available
        and validation_labels.statistics_available
        and selected_source_id in train_source.field_names
        and selected_label_id in validation_labels.field_names
    ):
        wrong_train_to_validation = _intersection_count(
            train_source.values_for(selected_source_id),
            validation_labels.values_for(selected_label_id),
        )
    if (
        selected_source_id is not None
        and selected_label_id is not None
        and validation_source.statistics_available
        and train_labels.statistics_available
        and selected_source_id in validation_source.field_names
        and selected_label_id in train_labels.field_names
    ):
        wrong_validation_to_train = _intersection_count(
            validation_source.values_for(selected_source_id),
            train_labels.values_for(selected_label_id),
        )

    return {
        "same_source_id_count": same_source_ids,
        "same_group_id_count": same_groups,
        "same_text_count": same_texts,
        "same_source_record_count": _intersection_count(
            train_source.row_digests,
            validation_source.row_digests,
        ),
        "train_source_validation_label_id_overlap_count": wrong_train_to_validation,
        "validation_source_train_label_id_overlap_count": wrong_validation_to_train,
    }


def _privacy_summary(
    *,
    train_source: InternalRecords,
    train_labels: InternalRecords,
    validation_source: InternalRecords,
    validation_labels: InternalRecords,
) -> dict[str, dict[str, int] | None]:
    def serialized(records: InternalRecords) -> dict[str, int] | None:
        if not records.statistics_available:
            return None
        return {
            name: int(records.privacy_counts.get(name, 0))
            for name in sorted(PRIVACY_PATTERNS)
        }

    return {
        "train_source": serialized(train_source),
        "train_labels": serialized(train_labels),
        "validation_source": serialized(validation_source),
        "validation_labels": serialized(validation_labels),
    }


def _is_unique_complete_key(records: InternalRecords, field_name: str) -> bool:
    values = records.values_for(field_name)
    return (
        records.record_count > 0
        and field_name in records.field_names
        and records.missing_for(field_name) == 0
        and _duplicate_count(values) == 0
        and sum(values.values()) == records.record_count
    )


def _resolve_join_fields(
    train_source: InternalRecords,
    train_labels: InternalRecords,
    validation_source: InternalRecords,
    validation_labels: InternalRecords,
    *,
    explicit_source_field: str | None,
    explicit_label_field: str | None,
) -> tuple[str | None, str | None, str]:
    if (explicit_source_field is None) != (explicit_label_field is None):
        raise AuditFailure("source and label ID fields must be supplied together")
    if explicit_source_field is not None and explicit_label_field is not None:
        return explicit_source_field, explicit_label_field, "explicit_id_fields"

    train_common = set(train_source.id_candidates) & set(train_labels.id_candidates)
    validation_common = set(validation_source.id_candidates) & set(
        validation_labels.id_candidates
    )
    common_across_splits = sorted(train_common & validation_common)
    if len(common_across_splits) == 1:
        selected = common_across_splits[0]
        if not all(
            _is_unique_complete_key(records, selected)
            for records in (
                train_source,
                train_labels,
                validation_source,
                validation_labels,
            )
        ):
            return None, None, "unresolved"
        if (
            _intersection_count(
                train_source.values_for(selected),
                train_labels.values_for(selected),
            )
            == 0
            or _intersection_count(
                validation_source.values_for(selected),
                validation_labels.values_for(selected),
            )
            == 0
        ):
            return None, None, "unresolved"
        return selected, selected, "common_id_candidate"
    return None, None, "unresolved"


def _validate_paths(
    train_source: Path,
    train_labels: Path,
    validation_source: Path,
    validation_labels: Path,
    output: Path,
) -> None:
    all_paths = (
        train_source,
        train_labels,
        validation_source,
        validation_labels,
        output,
    )
    if not all(path.is_absolute() for path in all_paths):
        raise AuditFailure("all input and output paths must be absolute")
    for source_path in (
        train_source,
        train_labels,
        validation_source,
        validation_labels,
    ):
        if not source_path.is_file():
            raise AuditFailure("a required input file is unavailable")
    if (
        train_source.suffix.casefold() != ".xlsx"
        or validation_source.suffix.casefold() != ".xlsx"
    ):
        raise AuditFailure("source inputs must be XLSX files")
    if (
        train_labels.suffix.casefold() != ".json"
        or validation_labels.suffix.casefold() != ".json"
    ):
        raise AuditFailure("label inputs must be JSON files")
    if not output.parent.is_dir():
        raise AuditFailure("the output directory is unavailable")
    resolved_inputs = {
        path.resolve()
        for path in (
            train_source,
            train_labels,
            validation_source,
            validation_labels,
        )
    }
    if len(resolved_inputs) != 4:
        raise AuditFailure("every official split input must be a separate file")
    if output.resolve() in resolved_inputs:
        raise AuditFailure("the output file must be separate from every input file")


def audit_dataset(
    *,
    train_source_xlsx: Path,
    train_label_json: Path,
    validation_source_xlsx: Path,
    validation_label_json: Path,
    options: AuditOptions,
) -> dict[str, Any]:
    """Audit explicitly supplied local files without returning source values."""

    train_source = _audit_xlsx(
        train_source_xlsx,
        source_sheet=options.source_sheet,
        explicit_id_field=options.source_id_field,
        explicit_text_field=options.text_field,
        explicit_group_field=options.group_field,
    )
    validation_source = _audit_xlsx(
        validation_source_xlsx,
        source_sheet=options.source_sheet,
        explicit_id_field=options.source_id_field,
        explicit_text_field=options.text_field,
        explicit_group_field=options.group_field,
    )
    train_labels = _audit_json(
        train_label_json,
        encoding=options.encoding,
        explicit_label_id_field=options.label_id_field,
        explicit_label_field=options.label_field,
        explicit_text_field=options.text_field,
        explicit_group_field=options.group_field,
    )
    validation_labels = _audit_json(
        validation_label_json,
        encoding=options.encoding,
        explicit_label_id_field=options.label_id_field,
        explicit_label_field=options.label_field,
        explicit_text_field=options.text_field,
        explicit_group_field=options.group_field,
    )

    source_join_field, label_join_field, strategy = _resolve_join_fields(
        train_source.records,
        train_labels.records,
        validation_source.records,
        validation_labels.records,
        explicit_source_field=options.source_id_field,
        explicit_label_field=options.label_id_field,
    )
    train_pairing = _pair_records(
        train_source.records,
        train_labels.records,
        source_field=source_join_field,
        label_field=label_join_field,
        strategy=strategy,
    )
    validation_pairing = _pair_records(
        validation_source.records,
        validation_labels.records,
        source_field=source_join_field,
        label_field=label_join_field,
        strategy=strategy,
    )

    audit_warnings = [
        *[f"train source: {message}" for message in train_source.warnings],
        *[f"train labels: {message}" for message in train_labels.warnings],
        *[f"validation source: {message}" for message in validation_source.warnings],
        *[f"validation labels: {message}" for message in validation_labels.warnings],
    ]
    limitations = list(
        dict.fromkeys(
            [
                *train_source.limitations,
                *train_labels.limitations,
                *validation_source.limitations,
                *validation_labels.limitations,
                "the audit reports structural evidence only and never approves label mapping",
                "JSON inspection loads one local label document into process memory",
                "cross-split digests are memory-only and are never serialized",
                "exact duplicate and leakage counts retain digests in memory in "
                "proportion to distinct audited records",
            ]
        )
    )

    return {
        "audit_version": AUDIT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_display_name": DATASET_DISPLAY_NAME,
        "splits": {
            "train": {
                "source_xlsx_summary": train_source.summary,
                "label_json_summary": train_labels.summary,
                "pairing_summary": train_pairing,
                "label_distribution": train_labels.label_distribution,
            },
            "validation": {
                "source_xlsx_summary": validation_source.summary,
                "label_json_summary": validation_labels.summary,
                "pairing_summary": validation_pairing,
                "label_distribution": validation_labels.label_distribution,
            },
        },
        "cross_split_leakage": _cross_split_leakage(
            train_source.records,
            train_labels.records,
            validation_source.records,
            validation_labels.records,
            source_id_field=source_join_field,
            label_id_field=label_join_field,
            text_field=options.text_field,
            group_field=options.group_field,
        ),
        "privacy_pattern_counts": _privacy_summary(
            train_source=train_source.records,
            train_labels=train_labels.records,
            validation_source=validation_source.records,
            validation_labels=validation_labels.records,
        ),
        "warnings": audit_warnings,
        "limitations": limitations,
    }


def _write_output(output_path: Path, payload: Mapping[str, object]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=".dataset-audit-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(
                payload,
                temporary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            temporary.write("\n")
        temporary_path.replace(output_path)
    except Exception as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise AuditFailure("the audit summary could not be written safely") from exc


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise AuditFailure("command arguments are invalid")


def _build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description=(
            "Audit local emotional-dialogue file structure without exposing "
            "source text, IDs, paths, or row-level records."
        )
    )
    parser.add_argument("--train-source-xlsx", required=True)
    parser.add_argument("--train-label-json", required=True)
    parser.add_argument("--validation-source-xlsx", required=True)
    parser.add_argument("--validation-label-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-id-field")
    parser.add_argument("--label-id-field")
    parser.add_argument("--text-field")
    parser.add_argument("--label-field")
    parser.add_argument("--group-field")
    parser.add_argument("--source-sheet")
    parser.add_argument("--encoding", default="utf-8-sig")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local audit and return a shell-compatible status code."""

    parser = _build_parser()
    try:
        arguments = parser.parse_args(argv)
        train_source = Path(arguments.train_source_xlsx)
        train_labels = Path(arguments.train_label_json)
        validation_source = Path(arguments.validation_source_xlsx)
        validation_labels = Path(arguments.validation_label_json)
        output = Path(arguments.output)
        _validate_paths(
            train_source,
            train_labels,
            validation_source,
            validation_labels,
            output,
        )
        options = AuditOptions(
            source_id_field=arguments.source_id_field,
            label_id_field=arguments.label_id_field,
            text_field=arguments.text_field,
            label_field=arguments.label_field,
            group_field=arguments.group_field,
            source_sheet=arguments.source_sheet,
            encoding=arguments.encoding,
        )
        result = audit_dataset(
            train_source_xlsx=train_source,
            train_label_json=train_labels,
            validation_source_xlsx=validation_source,
            validation_label_json=validation_labels,
            options=options,
        )
        _write_output(output, result)
    except AuditFailure as exc:
        print(f"Dataset audit failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print(
            "Dataset audit failed because of an unexpected local processing error",
            file=sys.stderr,
        )
        return 2

    print("Dataset audit completed", file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
