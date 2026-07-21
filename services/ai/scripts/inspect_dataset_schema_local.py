"""Value-safe local schema inspection for paired XLSX and JSON datasets.

This command is intentionally run by a human on their local machine. It emits
field names and aggregate statistics, but never serializes record values,
example text, identifiers, unmatched keys, hashes, digests, or input paths.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, NoReturn


AUDIT_VERSION = "local-schema-inspection-v1"
TYPE_NAMES = (
    "null",
    "string",
    "integer",
    "float",
    "boolean",
    "date_or_datetime",
    "other",
)
HEADER_SCAN_LIMIT = 10
EXACT_UNIQUE_LIMIT = 100_000
MAX_JSON_DEPTH = 20

PRIVACY_PATTERNS = (
    re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"),
    re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)"),
)

ROLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "conversation_id",
        (
            "conversation_id",
            "conversationid",
            "dialog_id",
            "dialogue_id",
            "대화_id",
            "대화id",
            "대화식별자",
        ),
    ),
    (
        "user_id",
        (
            "user_id",
            "userid",
            "speaker_id",
            "participant_id",
            "사용자_id",
            "사용자id",
            "사용자식별자",
            "화자_id",
        ),
    ),
    (
        "group_id",
        (
            "group_id",
            "groupid",
            "session_id",
            "document_id",
            "그룹_id",
            "그룹id",
            "세션_id",
            "문서_id",
        ),
    ),
    (
        "source_id",
        (
            "source_id",
            "sourceid",
            "record_id",
            "sample_id",
            "원천_id",
            "원천id",
            "원본_id",
            "레코드_id",
        ),
    ),
    (
        "label_id",
        (
            "label_id",
            "labelid",
            "annotation_id",
            "라벨_id",
            "라벨id",
            "어노테이션_id",
        ),
    ),
    (
        "utterance_text",
        (
            "utterance_text",
            "utterance",
            "sentence",
            "text",
            "content",
            "발화문",
            "발화",
            "문장",
            "원문",
            "텍스트",
        ),
    ),
    (
        "context_text",
        (
            "context_text",
            "context",
            "previous_text",
            "history",
            "문맥",
            "맥락",
            "이전문장",
            "대화이력",
        ),
    ),
    (
        "label",
        (
            "emotion_label",
            "class_label",
            "target_label",
            "label",
            "emotion",
            "class",
            "category",
            "감정라벨",
            "감정",
            "라벨",
            "분류",
            "범주",
        ),
    ),
    (
        "metadata",
        (
            "metadata",
            "meta",
            "attributes",
            "properties",
            "메타데이터",
            "부가정보",
            "속성",
        ),
    ),
)


class InspectionFailure(RuntimeError):
    """A caller-safe error that never contains a source path or record value."""


@dataclass
class LengthAccumulator:
    counts: Counter[int] = field(default_factory=Counter)

    def add(self, length: int) -> None:
        self.counts[length] += 1

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
            "p50": float(_length_at_quantile(self.counts, 0.50)),
            "p95": float(_length_at_quantile(self.counts, 0.95)),
        }


@dataclass
class ValueAccumulator:
    type_counts: Counter[str] = field(default_factory=Counter)
    string_lengths: LengthAccumulator = field(default_factory=LengthAccumulator)
    non_null_count: int = 0
    exact_values: set[tuple[str, object]] = field(default_factory=set)
    unique_overflow: bool = False
    selected_values: Counter[tuple[str, object]] | None = None
    structured_types: bool = False

    def add(self, value: object) -> None:
        value_type = _value_type(value, structured=self.structured_types)
        self.type_counts[value_type] += 1
        if value_type == "null":
            return
        self.non_null_count += 1
        if isinstance(value, str):
            self.string_lengths.add(len(value))
        canonical = _canonical_scalar(value)
        if canonical is not None:
            if self.selected_values is not None:
                self.selected_values[canonical] += 1
            if not self.unique_overflow:
                self.exact_values.add(canonical)
                if len(self.exact_values) > EXACT_UNIQUE_LIMIT:
                    self.exact_values.clear()
                    self.unique_overflow = True
        else:
            self.unique_overflow = True
            self.exact_values.clear()

    def unique_summary(self) -> dict[str, int | str]:
        if not self.unique_overflow:
            return {"kind": "exact", "count": len(self.exact_values)}
        return {"kind": "safe_upper_bound", "count": self.non_null_count}

    def public_summary(self, total_count: int) -> dict[str, object]:
        return {
            "type_counts": {name: self.type_counts.get(name, 0) for name in TYPE_NAMES},
            "missing_count": self.type_counts.get("null", 0),
            "non_null_count": self.non_null_count,
            "unique_count": self.unique_summary(),
            "string_length_statistics": self.string_lengths.summary(),
            "observed_value_count": total_count,
        }


@dataclass
class XlsxColumnInternal:
    position: int
    name: str
    header_cell: str | None
    values: ValueAccumulator


@dataclass
class XlsxSheetInternal:
    name: str
    state: str
    columns: list[XlsxColumnInternal]
    summary: dict[str, object]

    def resolve(self, reference: str) -> XlsxColumnInternal | None:
        if reference.isdecimal():
            position = int(reference)
            return next(
                (column for column in self.columns if column.position == position),
                None,
            )
        exact = [column for column in self.columns if column.name == reference]
        if len(exact) == 1:
            return exact[0]
        normalized = _normalize_name(reference)
        matches = [
            column
            for column in self.columns
            if _normalize_name(column.name) == normalized
        ]
        return matches[0] if len(matches) == 1 else None


@dataclass
class XlsxInspection:
    summary: dict[str, object]
    sheets: list[XlsxSheetInternal]

    @property
    def primary_sheet(self) -> XlsxSheetInternal | None:
        return next((sheet for sheet in self.sheets if sheet.state == "visible"), None)


@dataclass
class JsonFieldInternal:
    path: str
    present_records: set[int] = field(default_factory=set)
    values: ValueAccumulator = field(
        default_factory=lambda: ValueAccumulator(structured_types=True)
    )
    array_lengths: LengthAccumulator = field(default_factory=LengthAccumulator)
    child_keys: set[str] = field(default_factory=set)


@dataclass
class JsonInspection:
    summary: dict[str, object]
    fields: dict[str, JsonFieldInternal]
    record_count: int

    def resolve(self, reference: str) -> JsonFieldInternal | None:
        if reference in self.fields:
            return self.fields[reference]
        normalized = _normalize_name(reference)
        matches = [
            item
            for path, item in self.fields.items()
            if _normalize_name(_path_leaf(path)) == normalized
        ]
        return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class SplitOptions:
    header_row: int | None
    json_record_path: str | None
    xlsx_id_column: str | None
    json_id_field: str | None
    text_field: str | None
    group_field: str | None
    conversation_field: str | None


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _value_type(value: object, *, structured: bool = False) -> str:
    if _is_missing(value):
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, (date, datetime)):
        return "date_or_datetime"
    if isinstance(value, str):
        return "string"
    if structured and isinstance(value, Mapping):
        return "object"
    if structured and isinstance(value, list):
        return "array"
    return "other"


def _canonical_scalar(value: object) -> tuple[str, object] | None:
    if _is_missing(value):
        return None
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, int):
        return ("integer", value)
    if isinstance(value, float):
        numeric = value
        return ("float", numeric) if math.isfinite(numeric) else ("float", str(numeric))
    if isinstance(value, (date, datetime)):
        return ("date_or_datetime", value.isoformat())
    return None


def _length_at_quantile(counts: Counter[int], quantile: float) -> int:
    total = sum(counts.values())
    rank = max(0, math.ceil(quantile * total) - 1)
    seen = 0
    for length, frequency in sorted(counts.items()):
        seen += frequency
        if seen > rank:
            return length
    raise InspectionFailure("length statistics could not be completed safely")


def _normalize_name(name: str) -> str:
    return re.sub(r"[\s.\-/\[\]()]+", "_", name.strip().casefold()).strip("_")


def _path_leaf(path: str) -> str:
    leaf = path.rsplit(".", maxsplit=1)[-1]
    return leaf.removesuffix("[]")


def _safe_header_string(value: object) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return (
        bool(stripped)
        and len(stripped) <= 128
        and not any(character in stripped for character in "\r\n\t")
        and not any(pattern.search(stripped) for pattern in PRIVACY_PATTERNS)
    )


def _header_name_likelihood(value: object) -> float:
    if not _safe_header_string(value):
        return 0.0
    text = str(value).strip()
    normalized = _normalize_name(text)
    if not normalized:
        return 0.0
    if any(token in normalized for _, patterns in ROLE_PATTERNS for token in patterns):
        return 1.0
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_. -]{0,63}", text):
        return 0.8 if ("_" in text or text.isidentifier()) else 0.6
    if (
        len(text) <= 30
        and len(text.split()) <= 3
        and not any(character.isdigit() for character in text)
    ):
        return 0.65
    return 0.2


def _header_candidate_score(
    row: Sequence[object],
    following_rows: Sequence[Sequence[object]],
) -> tuple[float, dict[str, float]]:
    non_empty = [value for value in row if not _is_missing(value)]
    if not non_empty:
        return 0.0, {
            "string_ratio": 0.0,
            "unique_ratio": 0.0,
            "name_likelihood": 0.0,
            "type_difference_ratio": 0.0,
        }
    string_ratio = sum(isinstance(value, str) for value in non_empty) / len(non_empty)
    normalized_values = [
        _normalize_name(str(value)) if isinstance(value, str) else repr(type(value))
        for value in non_empty
    ]
    unique_ratio = len(set(normalized_values)) / len(normalized_values)
    name_likelihood = sum(_header_name_likelihood(value) for value in non_empty) / len(
        non_empty
    )
    comparable = 0
    differences = 0
    for following in following_rows[:5]:
        for index, header_value in enumerate(row):
            if index >= len(following) or _is_missing(following[index]):
                continue
            comparable += 1
            if _value_type(header_value) != _value_type(following[index]):
                differences += 1
    type_difference = differences / comparable if comparable else 0.0
    score = (
        0.35 * string_ratio
        + 0.25 * unique_ratio
        + 0.30 * name_likelihood
        + 0.10 * type_difference
    )
    return round(score, 3), {
        "string_ratio": round(string_ratio, 3),
        "unique_ratio": round(unique_ratio, 3),
        "name_likelihood": round(name_likelihood, 3),
        "type_difference_ratio": round(type_difference, 3),
    }


def _confidence(score: float) -> str:
    if score >= 0.82:
        return "high"
    if score >= 0.62:
        return "medium"
    return "low"


def _detect_header(
    rows: Sequence[Sequence[object]],
    explicit_row: int | None,
    max_row: int,
) -> dict[str, object]:
    if explicit_row is not None:
        if explicit_row < 1 or explicit_row > max_row:
            raise InspectionFailure(
                "an explicit XLSX header row is outside the worksheet"
            )
        if explicit_row > len(rows):
            raise InspectionFailure(
                "an explicit XLSX header row could not be inspected within the safe scan"
            )
        values = rows[explicit_row - 1]
        if not values or not all(
            _is_missing(value) or _safe_header_string(value) for value in values
        ):
            raise InspectionFailure(
                "an explicit XLSX header row contains an unsafe or non-string header"
            )
        return {
            "row_number": explicit_row,
            "status": "confirmed",
            "confidence": "high",
            "score": 1.0,
            "score_components": {"explicit_selection": 1.0},
            "values_may_be_exposed": True,
        }

    scored: list[tuple[float, int, dict[str, float]]] = []
    for index, row in enumerate(rows):
        score, components = _header_candidate_score(row, rows[index + 1 :])
        scored.append((score, index + 1, components))
    if not scored:
        return {
            "row_number": None,
            "status": "not_found",
            "confidence": "low",
            "score": 0.0,
            "score_components": {},
            "values_may_be_exposed": False,
        }
    score, detected_row_number, components = max(
        scored, key=lambda item: (item[0], -item[1])
    )
    row_number: int | None = detected_row_number
    row = rows[detected_row_number - 1]
    safe_and_unique = (
        bool(row)
        and all(_is_missing(value) or _safe_header_string(value) for value in row)
        and len(
            {_normalize_name(str(value)) for value in row if not _is_missing(value)}
        )
        == sum(not _is_missing(value) for value in row)
    )
    if score >= 0.82 and safe_and_unique:
        status = "confirmed"
    elif score >= 0.55:
        status = "candidate"
    else:
        status = "not_found"
        row_number = None
    return {
        "row_number": row_number,
        "status": status,
        "confidence": _confidence(score),
        "score": score,
        "score_components": components,
        "values_may_be_exposed": status == "confirmed" and safe_and_unique,
    }


def _safe_column_names(
    width: int,
    header_values: Sequence[object],
    expose_header: bool,
) -> tuple[list[str], list[str | None]]:
    names: list[str] = []
    header_cells: list[str | None] = []
    seen: Counter[str] = Counter()
    for index in range(width):
        value = header_values[index] if index < len(header_values) else None
        header_cell = (
            str(value).strip() if expose_header and _safe_header_string(value) else None
        )
        base_name = header_cell or f"column_{index + 1}"
        seen[base_name] += 1
        safe_name = (
            base_name if seen[base_name] == 1 else f"{base_name}_{seen[base_name]}"
        )
        names.append(safe_name)
        header_cells.append(header_cell)
    return names, header_cells


def _load_openpyxl() -> Any:
    try:
        return importlib.import_module("openpyxl")
    except ImportError as exc:
        raise InspectionFailure(
            "XLSX support is unavailable; install the declared dependency"
        ) from exc


def _inspect_xlsx(
    path: Path,
    logical_name: str,
    explicit_header_row: int | None,
    selected_columns: Iterable[str],
) -> XlsxInspection:
    openpyxl = _load_openpyxl()
    try:
        workbook = openpyxl.load_workbook(
            path,
            read_only=True,
            data_only=True,
        )
    except Exception as exc:
        raise InspectionFailure("an XLSX input could not be opened safely") from exc

    requested = {item for item in selected_columns if item}
    sheets: list[XlsxSheetInternal] = []
    try:
        for worksheet in workbook.worksheets:
            max_row = int(worksheet.max_row or 0)
            max_column = int(worksheet.max_column or 0)
            scan_rows = [
                tuple(row)
                for row in worksheet.iter_rows(
                    min_row=1,
                    max_row=min(max_row, HEADER_SCAN_LIMIT),
                    max_col=max_column or None,
                    values_only=True,
                )
            ]
            header = _detect_header(scan_rows, explicit_header_row, max_row)
            header_row = header["row_number"]
            header_values = (
                scan_rows[int(header_row) - 1]
                if isinstance(header_row, int) and header_row <= len(scan_rows)
                else ()
            )
            names, header_cells = _safe_column_names(
                max_column,
                header_values,
                bool(header["values_may_be_exposed"]),
            )
            accumulators: list[ValueAccumulator] = []
            for index, name in enumerate(names, start=1):
                role, _, _ = _role_for_name(name, False)
                selected = (
                    name in requested
                    or str(index) in requested
                    or (header_cells[index - 1] or "") in requested
                    or role
                    in {
                        "source_id",
                        "label_id",
                        "conversation_id",
                        "user_id",
                        "group_id",
                    }
                )
                accumulators.append(
                    ValueAccumulator(
                        selected_values=Counter() if selected else None,
                    )
                )
            data_start = int(header_row) + 1 if isinstance(header_row, int) else 1
            data_row_count = 0
            for row in worksheet.iter_rows(
                min_row=data_start,
                max_row=max_row,
                max_col=max_column or None,
                values_only=True,
            ):
                values = tuple(row)
                if not any(not _is_missing(value) for value in values):
                    continue
                data_row_count += 1
                for index, accumulator in enumerate(accumulators):
                    accumulator.add(values[index] if index < len(values) else None)

            columns: list[XlsxColumnInternal] = []
            column_summaries: list[dict[str, object]] = []
            for index, (name, header_cell, accumulator) in enumerate(
                zip(names, header_cells, accumulators, strict=True),
                start=1,
            ):
                columns.append(
                    XlsxColumnInternal(index, name, header_cell, accumulator)
                )
                column_summaries.append(
                    {
                        "position": index,
                        "name": name,
                        "header_cell": header_cell,
                        **accumulator.public_summary(data_row_count),
                    }
                )
            public_header = {
                key: value
                for key, value in header.items()
                if key != "values_may_be_exposed"
            }
            summary: dict[str, object] = {
                "name": worksheet.title,
                "state": worksheet.sheet_state,
                "max_row": max_row,
                "max_column": max_column,
                "header": public_header,
                "data_row_count": data_row_count,
                "columns": column_summaries,
            }
            sheets.append(
                XlsxSheetInternal(
                    name=worksheet.title,
                    state=worksheet.sheet_state,
                    columns=columns,
                    summary=summary,
                )
            )
    except InspectionFailure:
        raise
    except Exception as exc:
        raise InspectionFailure("an XLSX input could not be inspected safely") from exc
    finally:
        try:
            workbook.close()
        except Exception:
            pass

    return XlsxInspection(
        summary={
            "logical_name": logical_name,
            "sheet_count": len(sheets),
            "primary_sheet": (
                next((sheet.name for sheet in sheets if sheet.state == "visible"), None)
            ),
            "sheets": [sheet.summary for sheet in sheets],
        },
        sheets=sheets,
    )


def _top_level_type(value: object) -> str:
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    return _value_type(value)


def _json_path(parent: str, key: object) -> str:
    key_text = str(key)
    return f"{parent}.{key_text}" if parent != "$" else f"$.{key_text}"


def _discover_record_arrays(
    value: object,
    path: str = "$",
    depth: int = 0,
) -> dict[str, list[Mapping[str, object]]]:
    if depth > MAX_JSON_DEPTH:
        return {}
    candidates: dict[str, list[Mapping[str, object]]] = {}
    if isinstance(value, list):
        if not value or all(isinstance(item, Mapping) for item in value):
            candidates[path] = [item for item in value if isinstance(item, Mapping)]
        for item in value:
            if isinstance(item, (Mapping, list)):
                candidates.update(_discover_record_arrays(item, f"{path}[]", depth + 1))
    elif isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(nested, (Mapping, list)):
                candidates.update(
                    _discover_record_arrays(
                        nested,
                        _json_path(path, key),
                        depth + 1,
                    )
                )
    return candidates


def _discover_all_key_paths(
    value: object,
    path: str = "$",
    depth: int = 0,
) -> set[str]:
    if depth > MAX_JSON_DEPTH:
        return set()
    paths: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            nested_path = _json_path(path, key)
            paths.add(nested_path)
            if isinstance(nested, (Mapping, list)):
                paths.update(_discover_all_key_paths(nested, nested_path, depth + 1))
    elif isinstance(value, list):
        for nested in value:
            if isinstance(nested, (Mapping, list)):
                paths.update(_discover_all_key_paths(nested, f"{path}[]", depth + 1))
    return paths


def _select_record_array(
    candidates: Mapping[str, list[Mapping[str, object]]],
    explicit_path: str | None,
) -> tuple[str | None, list[Mapping[str, object]], str, bool]:
    if explicit_path is not None:
        if explicit_path not in candidates:
            raise InspectionFailure("an explicit JSON record path does not exist")
        return explicit_path, candidates[explicit_path], "high", True
    if not candidates:
        return None, [], "low", False
    if "$" in candidates:
        return "$", candidates["$"], "high", False
    preferred = [
        path
        for path in candidates
        if _path_leaf(path).casefold() in {"records", "data", "items"}
    ]
    if len(preferred) == 1:
        path = preferred[0]
        return path, candidates[path], "medium", False
    largest = max(candidates, key=lambda path: len(candidates[path]))
    return largest, candidates[largest], "low", False


def _field_for(
    fields: dict[str, JsonFieldInternal],
    path: str,
) -> JsonFieldInternal:
    if path not in fields:
        fields[path] = JsonFieldInternal(path=path)
    return fields[path]


def _walk_json_value(
    value: object,
    path: str,
    record_index: int,
    fields: dict[str, JsonFieldInternal],
    depth: int,
) -> None:
    if depth > MAX_JSON_DEPTH:
        return
    item = _field_for(fields, path)
    role, _, _ = _role_for_name(_path_leaf(path), False)
    if (
        role
        in {
            "source_id",
            "label_id",
            "conversation_id",
            "user_id",
            "group_id",
        }
        and item.values.selected_values is None
    ):
        item.values.selected_values = Counter()
    item.present_records.add(record_index)
    item.values.add(value)
    if isinstance(value, list):
        item.array_lengths.add(len(value))
        for nested in value:
            if isinstance(nested, Mapping):
                for key, child in nested.items():
                    _walk_json_value(
                        child,
                        _json_path(f"{path}[]", key),
                        record_index,
                        fields,
                        depth + 1,
                    )
            elif isinstance(nested, list):
                _walk_json_value(
                    nested,
                    f"{path}[]",
                    record_index,
                    fields,
                    depth + 1,
                )
    elif isinstance(value, Mapping):
        item.child_keys.update(str(key) for key in value)
        for key, child in value.items():
            _walk_json_value(
                child,
                _json_path(path, key),
                record_index,
                fields,
                depth + 1,
            )


def _inspect_json(
    path: Path,
    logical_name: str,
    explicit_record_path: str | None,
    selected_fields: Iterable[str],
) -> JsonInspection:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InspectionFailure("a JSON input could not be decoded safely") from exc
    except Exception as exc:
        raise InspectionFailure("a JSON input could not be opened safely") from exc

    candidates = _discover_record_arrays(payload)
    all_key_paths = _discover_all_key_paths(payload)
    selected_path, records, confidence, was_explicit = _select_record_array(
        candidates,
        explicit_record_path,
    )
    selected_normalized = {_normalize_name(item) for item in selected_fields if item}
    fields: dict[str, JsonFieldInternal] = {}
    root_prefix = (
        "$"
        if selected_path == "$"
        else f"{selected_path}[]"
        if selected_path is not None
        else "$"
    )
    for record_index, record in enumerate(records):
        for key, value in record.items():
            field_path = _json_path(root_prefix, key)
            item = _field_for(fields, field_path)
            if (
                _normalize_name(field_path) in selected_normalized
                or _normalize_name(str(key)) in selected_normalized
            ) and item.values.selected_values is None:
                item.values.selected_values = Counter()
            _walk_json_value(value, field_path, record_index, fields, 0)

    public_fields: list[dict[str, object]] = []
    for field_path, item in sorted(fields.items()):
        public_fields.append(
            {
                "path": field_path,
                "presence_count": len(item.present_records),
                "missing_count": len(records) - len(item.present_records),
                "type_counts": dict(sorted(item.values.type_counts.items())),
                "string_length_statistics": item.values.string_lengths.summary(),
                "array_length_statistics": item.array_lengths.summary(),
                "child_keys": sorted(item.child_keys),
            }
        )
    return JsonInspection(
        summary={
            "logical_name": logical_name,
            "top_level_type": _top_level_type(payload),
            "record_array_candidates": [
                {
                    "path": candidate,
                    "record_count": len(candidate_records),
                    "approved": False,
                }
                for candidate, candidate_records in sorted(candidates.items())
            ],
            "selected_record_path": selected_path,
            "selection_confidence": confidence,
            "selection_was_explicit": was_explicit,
            "approved": False,
            "record_count": len(records),
            "all_key_paths": sorted(all_key_paths),
            "fields": public_fields,
        },
        fields=fields,
        record_count=len(records),
    )


def _role_for_name(name: str, structured: bool) -> tuple[str, str, str]:
    normalized = _normalize_name(name)
    for role, patterns in ROLE_PATTERNS:
        exact = normalized in {_normalize_name(pattern) for pattern in patterns}
        if exact:
            return role, "field name exactly matches a role pattern", "high"
    matches: list[str] = []
    for role, patterns in ROLE_PATTERNS:
        if any(_normalize_name(pattern) in normalized for pattern in patterns):
            matches.append(role)
    if len(matches) == 1:
        return matches[0], "field name contains one role pattern", "medium"
    if structured:
        return "metadata", "field has an object or array structure", "low"
    return "unknown", "field name and structure are ambiguous", "low"


def _role_candidates(
    xlsx: XlsxInspection,
    json_result: JsonInspection,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    primary = xlsx.primary_sheet
    if primary is not None:
        for column in primary.columns:
            role, reason, confidence = _role_for_name(column.name, False)
            candidates.append(
                {
                    "origin": "xlsx",
                    "sheet": primary.name,
                    "field": column.name,
                    "column_position": column.position,
                    "candidate_role": role,
                    "reason": reason,
                    "confidence": confidence,
                    "approved": False,
                }
            )
    for path, item in sorted(json_result.fields.items()):
        structured = bool(item.child_keys) or bool(item.array_lengths.counts)
        role, reason, confidence = _role_for_name(_path_leaf(path), structured)
        candidates.append(
            {
                "origin": "json",
                "field": path,
                "candidate_role": role,
                "reason": reason,
                "confidence": confidence,
                "approved": False,
            }
        )
    return candidates


def _counter_for_xlsx(column: XlsxColumnInternal) -> Counter[tuple[str, object]]:
    return column.values.selected_values or Counter()


def _counter_for_json(field_item: JsonFieldInternal) -> Counter[tuple[str, object]]:
    return field_item.values.selected_values or Counter()


def _duplicate_count(values: Counter[tuple[str, object]]) -> int:
    return sum(max(0, count - 1) for count in values.values())


def _join_statistics(
    xlsx_column: XlsxColumnInternal,
    json_field: JsonFieldInternal,
    confidence: str,
    reason: str,
) -> dict[str, object]:
    xlsx_values = _counter_for_xlsx(xlsx_column)
    json_values = _counter_for_json(json_field)
    xlsx_keys = set(xlsx_values)
    json_keys = set(json_values)
    intersection = xlsx_keys & json_keys
    xlsx_unique = len(xlsx_keys)
    json_unique = len(json_keys)
    xlsx_duplicates = _duplicate_count(xlsx_values)
    json_duplicates = _duplicate_count(json_values)
    if xlsx_duplicates == 0 and json_duplicates == 0:
        relation = "one_to_one_candidate"
    elif xlsx_duplicates == 0:
        relation = "one_to_many_candidate"
    elif json_duplicates == 0:
        relation = "many_to_one_candidate"
    else:
        relation = "many_to_many_or_invalid"
    denominator = max(xlsx_unique, json_unique)
    return {
        "xlsx_column": xlsx_column.name,
        "xlsx_column_position": xlsx_column.position,
        "json_field": json_field.path,
        "reason": reason,
        "xlsx_non_null_count": sum(xlsx_values.values()),
        "json_non_null_count": sum(json_values.values()),
        "xlsx_unique_count": xlsx_unique,
        "json_unique_count": json_unique,
        "xlsx_duplicate_key_count": xlsx_duplicates,
        "json_duplicate_key_count": json_duplicates,
        "intersection_count": len(intersection),
        "xlsx_only_count": len(xlsx_keys - json_keys),
        "json_only_count": len(json_keys - xlsx_keys),
        "match_rate": round(len(intersection) / denominator, 6) if denominator else 0.0,
        "relationship": relation,
        "confidence": confidence,
        "approved": False,
    }


def _join_candidates(
    xlsx: XlsxInspection,
    json_result: JsonInspection,
    explicit_xlsx: str | None,
    explicit_json: str | None,
) -> list[dict[str, object]]:
    primary = xlsx.primary_sheet
    if primary is None:
        if explicit_xlsx or explicit_json:
            raise InspectionFailure(
                "an explicit join field requires a visible worksheet"
            )
        return []
    if (explicit_xlsx is None) != (explicit_json is None):
        raise InspectionFailure(
            "explicit XLSX and JSON join fields must be provided together"
        )
    if explicit_xlsx is not None and explicit_json is not None:
        xlsx_column = primary.resolve(explicit_xlsx)
        json_field = json_result.resolve(explicit_json)
        if xlsx_column is None:
            raise InspectionFailure("an explicit XLSX ID column does not exist")
        if json_field is None:
            raise InspectionFailure("an explicit JSON ID field does not exist")
        return [
            _join_statistics(
                xlsx_column,
                json_field,
                "high",
                "both join fields were explicitly selected",
            )
        ]

    candidates: list[dict[str, object]] = []
    for column in primary.columns:
        xlsx_role, _, _ = _role_for_name(column.name, False)
        if xlsx_role not in {
            "source_id",
            "label_id",
            "conversation_id",
            "user_id",
            "group_id",
        }:
            continue
        for path, field_item in json_result.fields.items():
            json_role, _, _ = _role_for_name(_path_leaf(path), False)
            exact_name = _normalize_name(column.name) == _normalize_name(
                _path_leaf(path)
            )
            compatible_id = xlsx_role == json_role or {
                xlsx_role,
                json_role,
            } == {"source_id", "label_id"}
            if not exact_name and not compatible_id:
                continue
            confidence = "medium" if exact_name else "low"
            candidates.append(
                _join_statistics(
                    column,
                    field_item,
                    confidence,
                    "field names match"
                    if exact_name
                    else "field-name roles are structurally compatible",
                )
            )
    return candidates


def _resolve_cross_field(
    reference: str,
    xlsx: XlsxInspection,
    json_result: JsonInspection,
) -> Counter[tuple[str, object]]:
    primary = xlsx.primary_sheet
    origin: str | None = None
    field_reference = reference
    if reference.startswith("xlsx:"):
        origin = "xlsx"
        field_reference = reference.removeprefix("xlsx:")
    elif reference.startswith("json:"):
        origin = "json"
        field_reference = reference.removeprefix("json:")
    xlsx_field = (
        primary.resolve(field_reference)
        if primary is not None and origin != "json"
        else None
    )
    json_field = json_result.resolve(field_reference) if origin != "xlsx" else None
    if xlsx_field is not None and json_field is not None:
        raise InspectionFailure("an explicit cross-split field is ambiguous")
    if xlsx_field is not None:
        return _counter_for_xlsx(xlsx_field)
    if json_field is not None:
        return _counter_for_json(json_field)
    raise InspectionFailure("an explicit cross-split field does not exist")


def _overlap_summary(
    train_values: Counter[tuple[str, object]],
    validation_values: Counter[tuple[str, object]],
) -> dict[str, int | float | str]:
    train_keys = set(train_values)
    validation_keys = set(validation_values)
    overlap = train_keys & validation_keys
    return {
        "status": "completed",
        "train_non_null_count": sum(train_values.values()),
        "validation_non_null_count": sum(validation_values.values()),
        "train_unique_count": len(train_keys),
        "validation_unique_count": len(validation_keys),
        "overlap_count": len(overlap),
        "train_overlap_rate": round(len(overlap) / len(train_keys), 6)
        if train_keys
        else 0.0,
        "validation_overlap_rate": round(len(overlap) / len(validation_keys), 6)
        if validation_keys
        else 0.0,
    }


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = re.sub(r"\s+", " ", normalized.strip())
    return re.sub(r"[A-Z]", lambda match: match.group(0).lower(), normalized)


def _normalized_text_counter(
    values: Counter[tuple[str, object]],
) -> Counter[tuple[str, object]]:
    normalized: Counter[tuple[str, object]] = Counter()
    for (value_type, value), count in values.items():
        if value_type == "string":
            text = _normalize_text(str(value))
            if text:
                normalized[("string", text)] += count
    return normalized


def _cross_split_checks(
    train_xlsx: XlsxInspection,
    train_json: JsonInspection,
    validation_xlsx: XlsxInspection,
    validation_json: JsonInspection,
    train_options: SplitOptions,
    validation_options: SplitOptions,
) -> dict[str, object]:
    checks: dict[str, object] = {}

    def add_check(
        name: str,
        train_reference: str | None,
        validation_reference: str | None,
        normalize_text: bool = False,
    ) -> None:
        if train_reference is None and validation_reference is None:
            checks[name] = {
                "status": "not_run",
                "reason": "fields were not explicitly selected",
            }
            return
        if train_reference is None or validation_reference is None:
            raise InspectionFailure(
                "both split fields are required for a cross-split check"
            )
        train_values = _resolve_cross_field(
            train_reference,
            train_xlsx,
            train_json,
        )
        validation_values = _resolve_cross_field(
            validation_reference,
            validation_xlsx,
            validation_json,
        )
        if normalize_text:
            train_values = _normalized_text_counter(train_values)
            validation_values = _normalized_text_counter(validation_values)
        checks[name] = _overlap_summary(train_values, validation_values)

    add_check(
        "source_id_overlap",
        train_options.xlsx_id_column,
        validation_options.xlsx_id_column,
    )
    add_check(
        "group_id_overlap",
        train_options.group_field,
        validation_options.group_field,
    )
    add_check(
        "conversation_id_overlap",
        train_options.conversation_field,
        validation_options.conversation_field,
    )
    add_check(
        "normalized_text_overlap",
        train_options.text_field,
        validation_options.text_field,
        normalize_text=True,
    )
    return checks


def _decision(
    decision: str,
    split: str | None,
    candidates: Sequence[object],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "decision": decision,
        "status": "required",
        "candidates": list(candidates),
    }
    if split is not None:
        payload["split"] = split
    return payload


def _decisions_required(
    train: dict[str, object],
    validation: dict[str, object],
) -> list[dict[str, object]]:
    decisions: list[dict[str, object]] = []
    for split_name, result in (("train", train), ("validation", validation)):
        xlsx = result["xlsx_schema"]
        json_schema = result["json_schema"]
        roles = result["role_candidates"]
        joins = result["join_candidates"]
        assert isinstance(xlsx, Mapping)
        assert isinstance(json_schema, Mapping)
        assert isinstance(roles, list)
        assert isinstance(joins, list)
        sheets = xlsx.get("sheets", [])
        header_candidates = []
        if isinstance(sheets, list):
            for sheet in sheets:
                if isinstance(sheet, Mapping):
                    header_candidates.append(
                        {
                            "sheet": sheet.get("name"),
                            "header": sheet.get("header"),
                        }
                    )
        decisions.extend(
            [
                _decision("approve_xlsx_header", split_name, header_candidates),
                _decision(
                    "select_json_record_path",
                    split_name,
                    list(json_schema.get("record_array_candidates", [])),
                ),
                _decision(
                    "select_text_field",
                    split_name,
                    [
                        item
                        for item in roles
                        if isinstance(item, Mapping)
                        and item.get("candidate_role")
                        in {"utterance_text", "context_text"}
                    ],
                ),
                _decision(
                    "select_label_field",
                    split_name,
                    [
                        item
                        for item in roles
                        if isinstance(item, Mapping)
                        and item.get("candidate_role") == "label"
                    ],
                ),
                _decision(
                    "approve_join_key",
                    split_name,
                    joins,
                ),
            ]
        )
    decisions.append(
        _decision(
            "approve_split_grouping_and_leakage_policy",
            None,
            [
                "source_id",
                "group_id",
                "conversation_id",
                "normalized_text",
            ],
        )
    )
    return decisions


def _inspect_split(
    split_name: str,
    xlsx_path: Path,
    json_path: Path,
    options: SplitOptions,
) -> tuple[dict[str, object], XlsxInspection, JsonInspection]:
    def reference_for_origin(reference: str | None, origin: str) -> str | None:
        if reference is None:
            return None
        if reference.startswith("xlsx:"):
            return reference.removeprefix("xlsx:") if origin == "xlsx" else None
        if reference.startswith("json:"):
            return reference.removeprefix("json:") if origin == "json" else None
        return reference

    selected_xlsx_fields = {
        item
        for item in (
            options.xlsx_id_column,
            reference_for_origin(options.text_field, "xlsx"),
            reference_for_origin(options.group_field, "xlsx"),
            reference_for_origin(options.conversation_field, "xlsx"),
        )
        if item is not None
    }
    selected_json_fields = {
        item
        for item in (
            options.json_id_field,
            reference_for_origin(options.text_field, "json"),
            reference_for_origin(options.group_field, "json"),
            reference_for_origin(options.conversation_field, "json"),
        )
        if item is not None
    }
    xlsx = _inspect_xlsx(
        xlsx_path,
        f"{split_name}_source_xlsx",
        options.header_row,
        selected_xlsx_fields,
    )
    json_result = _inspect_json(
        json_path,
        f"{split_name}_label_json",
        options.json_record_path,
        selected_json_fields,
    )
    roles = _role_candidates(xlsx, json_result)
    joins = _join_candidates(
        xlsx,
        json_result,
        options.xlsx_id_column,
        options.json_id_field,
    )
    result: dict[str, object] = {
        "xlsx_schema": xlsx.summary,
        "json_schema": json_result.summary,
        "role_candidates": roles,
        "join_candidates": joins,
    }
    return result, xlsx, json_result


def inspect_dataset_schema(
    *,
    train_source_xlsx: Path,
    train_label_json: Path,
    validation_source_xlsx: Path,
    validation_label_json: Path,
    train_options: SplitOptions,
    validation_options: SplitOptions,
) -> dict[str, object]:
    train, train_xlsx, train_json = _inspect_split(
        "train",
        train_source_xlsx,
        train_label_json,
        train_options,
    )
    validation, validation_xlsx, validation_json = _inspect_split(
        "validation",
        validation_source_xlsx,
        validation_label_json,
        validation_options,
    )
    splits = {"train": train, "validation": validation}
    return {
        "audit_version": AUDIT_VERSION,
        "safe_output_policy": {
            "record_values_serialized": False,
            "text_examples_serialized": False,
            "identifier_values_serialized": False,
            "unmatched_keys_serialized": False,
            "hashes_or_digests_serialized": False,
            "absolute_input_paths_serialized": False,
            "field_names_and_aggregate_statistics_only": True,
            "automatic_candidates_approved": False,
        },
        "splits": splits,
        "cross_split_checks": _cross_split_checks(
            train_xlsx,
            train_json,
            validation_xlsx,
            validation_json,
            train_options,
            validation_options,
        ),
        "decisions_required": _decisions_required(train, validation),
        "warnings": [
            "header and field roles are structural candidates until a human approves them",
            "automatic JSON record-path selection is not an approval",
            "cross-split checks run only for fields explicitly supplied on the command line",
            "the first visible worksheet is the primary sheet for role and join candidates",
        ],
        "limitations": [
            "field-name patterns do not establish label meaning",
            "unique-value tracking may switch to a safe upper bound for high-cardinality fields",
            "JSON is loaded into local process memory for structural inspection",
            "join and overlap values are retained only in memory and are never serialized",
            "semantic and near-duplicate text leakage requires an approved separate policy",
        ],
    }


def _validate_paths(paths: Sequence[Path], output: Path) -> None:
    if not all(path.is_absolute() for path in (*paths, output)):
        raise InspectionFailure("all input and output paths must be absolute")
    if not all(path.is_file() for path in paths):
        raise InspectionFailure("a required input file is unavailable")
    if paths[0].suffix.casefold() != ".xlsx" or paths[2].suffix.casefold() != ".xlsx":
        raise InspectionFailure("source inputs must be XLSX files")
    if paths[1].suffix.casefold() != ".json" or paths[3].suffix.casefold() != ".json":
        raise InspectionFailure("label inputs must be JSON files")
    if not output.parent.is_dir():
        raise InspectionFailure("the output directory is unavailable")
    resolved_inputs = {path.resolve() for path in paths}
    if len(resolved_inputs) != len(paths):
        raise InspectionFailure("every split input must be a separate file")
    if output.resolve() in resolved_inputs:
        raise InspectionFailure("the output file must be separate from all inputs")


def _write_output(output: Path, payload: Mapping[str, object]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=".schema-inspection-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary_path.replace(output)
    except Exception as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise InspectionFailure(
            "the schema report could not be written safely"
        ) from exc


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise InspectionFailure("command arguments are invalid")


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description=(
            "Inspect local XLSX and JSON schema without emitting record values, "
            "identifiers, text examples, hashes, or input paths."
        )
    )
    parser.add_argument("--train-source-xlsx", required=True)
    parser.add_argument("--train-label-json", required=True)
    parser.add_argument("--validation-source-xlsx", required=True)
    parser.add_argument("--validation-label-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--train-xlsx-header-row", type=_positive_integer)
    parser.add_argument("--validation-xlsx-header-row", type=_positive_integer)
    parser.add_argument("--train-json-record-path")
    parser.add_argument("--validation-json-record-path")
    parser.add_argument("--train-xlsx-id-column")
    parser.add_argument("--train-json-id-field")
    parser.add_argument("--validation-xlsx-id-column")
    parser.add_argument("--validation-json-id-field")
    parser.add_argument("--train-text-field")
    parser.add_argument("--validation-text-field")
    parser.add_argument("--train-group-field")
    parser.add_argument("--validation-group-field")
    parser.add_argument("--train-conversation-field")
    parser.add_argument("--validation-conversation-field")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        arguments = parser.parse_args(argv)
        input_paths = (
            Path(arguments.train_source_xlsx),
            Path(arguments.train_label_json),
            Path(arguments.validation_source_xlsx),
            Path(arguments.validation_label_json),
        )
        output = Path(arguments.output)
        _validate_paths(input_paths, output)
        train_options = SplitOptions(
            header_row=arguments.train_xlsx_header_row,
            json_record_path=arguments.train_json_record_path,
            xlsx_id_column=arguments.train_xlsx_id_column,
            json_id_field=arguments.train_json_id_field,
            text_field=arguments.train_text_field,
            group_field=arguments.train_group_field,
            conversation_field=arguments.train_conversation_field,
        )
        validation_options = SplitOptions(
            header_row=arguments.validation_xlsx_header_row,
            json_record_path=arguments.validation_json_record_path,
            xlsx_id_column=arguments.validation_xlsx_id_column,
            json_id_field=arguments.validation_json_id_field,
            text_field=arguments.validation_text_field,
            group_field=arguments.validation_group_field,
            conversation_field=arguments.validation_conversation_field,
        )
        result = inspect_dataset_schema(
            train_source_xlsx=input_paths[0],
            train_label_json=input_paths[1],
            validation_source_xlsx=input_paths[2],
            validation_label_json=input_paths[3],
            train_options=train_options,
            validation_options=validation_options,
        )
        _write_output(output, result)
    except InspectionFailure as exc:
        print(f"Schema inspection failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print(
            "Schema inspection failed because of an unexpected local processing error",
            file=sys.stderr,
        )
        return 2
    print("Schema inspection completed", file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
