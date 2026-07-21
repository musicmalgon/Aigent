"""Synthetic-only tests for the value-safe local schema inspector."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from collections.abc import Sequence

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "ai" / "scripts" / "inspect_dataset_schema_local.py"


@dataclass(frozen=True)
class SyntheticFiles:
    train_xlsx: Path
    train_json: Path
    validation_xlsx: Path
    validation_json: Path
    output: Path
    sensitive_values: tuple[str, ...]


def _openpyxl() -> Any:
    return pytest.importorskip("openpyxl")


def _write_xlsx(
    path: Path,
    rows: Sequence[Sequence[object]],
    *,
    header: Sequence[object] | None = None,
    title: str | None = None,
) -> None:
    openpyxl = _openpyxl()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "SyntheticRecords"
    if title is not None:
        sheet.append([title])
    if header is not None:
        sheet.append(header)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(scope="module")
def inspector() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_schema_inspector_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def synthetic_files(tmp_path: Path) -> SyntheticFiles:
    header = [
        "source_id",
        "conversation_id",
        "group_id",
        "utterance_text",
        "mixed_value",
        "very_long_text",
    ]
    long_secret = "LONG_PRIVATE_SYNTHETIC_TEXT_" * 2_000
    train_rows: list[list[object]] = [
        [
            "PRIVATE-TRAIN-ID-01",
            "PRIVATE-CONVERSATION-SHARED",
            "PRIVATE-GROUP-01",
            "PRIVATE Synthetic Sentence Alpha",
            1,
            long_secret,
        ],
        [
            "PRIVATE-TRAIN-ID-02",
            "PRIVATE-CONVERSATION-02",
            "PRIVATE-GROUP-02",
            "PRIVATE Synthetic Sentence Beta",
            "PRIVATE-MIXED-VALUE",
            "",
        ],
    ]
    validation_rows: list[list[object]] = [
        [
            "PRIVATE-VALID-ID-01",
            "PRIVATE-CONVERSATION-SHARED",
            "PRIVATE-GROUP-03",
            "  private synthetic sentence alpha  ",
            2.5,
            "",
        ],
        [
            "PRIVATE-VALID-ID-02",
            "PRIVATE-CONVERSATION-04",
            "PRIVATE-GROUP-04",
            "PRIVATE Synthetic Sentence Gamma",
            True,
            "",
        ],
    ]
    train_labels = {
        "bundle": {
            "records": [
                {
                    "label_id": train_rows[0][0],
                    "annotation": {"감정라벨": "PRIVATE-LABEL-A"},
                    "items": [{"attribute_name": "PRIVATE-ATTRIBUTE-A"}],
                },
                {
                    "label_id": train_rows[1][0],
                    "annotation": {"감정라벨": "PRIVATE-LABEL-B"},
                    "items": [{"attribute_name": "PRIVATE-ATTRIBUTE-B"}],
                },
            ]
        }
    }
    validation_labels = {
        "bundle": {
            "records": [
                {
                    "label_id": validation_rows[0][0],
                    "annotation": {"감정라벨": "PRIVATE-LABEL-C"},
                    "items": [],
                },
                {
                    "label_id": validation_rows[1][0],
                    "annotation": {"감정라벨": "PRIVATE-LABEL-D"},
                    "items": [],
                },
            ]
        }
    }
    train_xlsx = tmp_path / "synthetic_train.xlsx"
    train_json = tmp_path / "synthetic_train.json"
    validation_xlsx = tmp_path / "synthetic_validation.xlsx"
    validation_json = tmp_path / "synthetic_validation.json"
    _write_xlsx(train_xlsx, train_rows, header=header)
    _write_xlsx(validation_xlsx, validation_rows, header=header)
    _write_json(train_json, train_labels)
    _write_json(validation_json, validation_labels)
    sensitive = tuple(
        str(value)
        for row in [*train_rows, *validation_rows]
        for value in row
        if isinstance(value, str) and value
    ) + (
        "PRIVATE-LABEL-A",
        "PRIVATE-LABEL-B",
        "PRIVATE-LABEL-C",
        "PRIVATE-LABEL-D",
        "PRIVATE-ATTRIBUTE-A",
        "PRIVATE-ATTRIBUTE-B",
    )
    return SyntheticFiles(
        train_xlsx=train_xlsx,
        train_json=train_json,
        validation_xlsx=validation_xlsx,
        validation_json=validation_json,
        output=tmp_path / "schema_report.json",
        sensitive_values=sensitive,
    )


def _args(files: SyntheticFiles, *extra: str) -> list[str]:
    return [
        "--train-source-xlsx",
        str(files.train_xlsx),
        "--train-label-json",
        str(files.train_json),
        "--validation-source-xlsx",
        str(files.validation_xlsx),
        "--validation-label-json",
        str(files.validation_json),
        "--output",
        str(files.output),
        *extra,
    ]


def _run(
    inspector: ModuleType,
    files: SyntheticFiles,
    capsys: pytest.CaptureFixture[str],
    *extra: str,
) -> tuple[int, dict[str, Any] | None, str]:
    code = inspector.main(_args(files, *extra))
    captured = capsys.readouterr()
    payload = (
        json.loads(files.output.read_text(encoding="utf-8"))
        if files.output.exists()
        else None
    )
    return code, payload, captured.out + captured.err


def test_header_detection_nested_json_and_safe_output(
    inspector: ModuleType,
    synthetic_files: SyntheticFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload, console = _run(inspector, synthetic_files, capsys)
    assert code == 0
    assert payload is not None
    train = payload["splits"]["train"]
    sheet = train["xlsx_schema"]["sheets"][0]
    assert sheet["header"]["row_number"] == 1
    assert sheet["header"]["status"] == "confirmed"
    assert sheet["columns"][0]["header_cell"] == "source_id"
    json_schema = train["json_schema"]
    assert json_schema["selected_record_path"] == "$.bundle.records"
    assert "$.bundle" in json_schema["all_key_paths"]
    assert "$.bundle.records" in json_schema["all_key_paths"]
    paths = {item["path"] for item in json_schema["fields"]}
    assert "$.bundle.records[].annotation.감정라벨" in paths
    assert "$.bundle.records[].items[].attribute_name" in paths

    serialized = json.dumps(payload, ensure_ascii=False)
    combined = serialized + console
    for value in synthetic_files.sensitive_values:
        assert value not in combined
    for path in (
        synthetic_files.train_xlsx,
        synthetic_files.train_json,
        synthetic_files.validation_xlsx,
        synthetic_files.validation_json,
    ):
        assert str(path) not in combined
    assert payload["safe_output_policy"]["hashes_or_digests_serialized"] is False
    assert re.search(r"\b[0-9a-fA-F]{64}\b", serialized) is None


def test_explicit_header_and_record_path(
    inspector: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = _minimal_files(tmp_path, title="SYNTHETIC PRIVATE TITLE")
    code, payload, _ = _run(
        inspector,
        files,
        capsys,
        "--train-xlsx-header-row",
        "2",
        "--validation-xlsx-header-row",
        "2",
        "--train-json-record-path",
        "$.records",
        "--validation-json-record-path",
        "$.records",
    )
    assert code == 0
    assert payload is not None
    for split in ("train", "validation"):
        header = payload["splits"][split]["xlsx_schema"]["sheets"][0]["header"]
        assert header["row_number"] == 2
        assert header["status"] == "confirmed"
        assert header["score_components"] == {"explicit_selection": 1.0}
        schema = payload["splits"][split]["json_schema"]
        assert schema["selection_was_explicit"] is True


def _minimal_files(
    tmp_path: Path,
    *,
    title: str | None = None,
    duplicate_train_key: bool = False,
) -> SyntheticFiles:
    header = ["source_id", "utterance_text"]
    train_rows: list[list[object]] = [
        ["PRIVATE-A" if not duplicate_train_key else "PRIVATE-DUP", "PRIVATE TEXT A"],
        ["PRIVATE-B" if not duplicate_train_key else "PRIVATE-DUP", "PRIVATE TEXT B"],
    ]
    validation_rows: list[list[object]] = [["PRIVATE-C", "PRIVATE TEXT C"]]
    train_records = [
        {"label_id": row[0], "감정라벨": f"PRIVATE-LABEL-{index}"}
        for index, row in enumerate(train_rows)
    ]
    validation_records = [
        {"label_id": validation_rows[0][0], "감정라벨": "PRIVATE-LABEL-V"}
    ]
    paths = {
        "train_xlsx": tmp_path / "train.xlsx",
        "train_json": tmp_path / "train.json",
        "validation_xlsx": tmp_path / "validation.xlsx",
        "validation_json": tmp_path / "validation.json",
    }
    _write_xlsx(paths["train_xlsx"], train_rows, header=header, title=title)
    _write_xlsx(
        paths["validation_xlsx"],
        validation_rows,
        header=header,
        title=title,
    )
    _write_json(paths["train_json"], {"records": train_records})
    _write_json(paths["validation_json"], {"records": validation_records})
    return SyntheticFiles(
        **paths,
        output=tmp_path / "output.json",
        sensitive_values=(
            "PRIVATE-A",
            "PRIVATE-B",
            "PRIVATE-C",
            "PRIVATE-DUP",
            "PRIVATE TEXT A",
            "PRIVATE TEXT B",
            "PRIVATE TEXT C",
            "PRIVATE-LABEL-0",
            "PRIVATE-LABEL-1",
            "PRIVATE-LABEL-V",
        ),
    )


def test_explicit_join_statistics_and_one_to_one(
    inspector: ModuleType,
    synthetic_files: SyntheticFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload, _ = _run(
        inspector,
        synthetic_files,
        capsys,
        "--train-xlsx-id-column",
        "source_id",
        "--train-json-id-field",
        "label_id",
        "--validation-xlsx-id-column",
        "source_id",
        "--validation-json-id-field",
        "label_id",
    )
    assert code == 0
    assert payload is not None
    for split in ("train", "validation"):
        join = payload["splits"][split]["join_candidates"][0]
        assert join["intersection_count"] == 2
        assert join["xlsx_only_count"] == 0
        assert join["json_only_count"] == 0
        assert join["match_rate"] == 1.0
        assert join["relationship"] == "one_to_one_candidate"
        assert join["approved"] is False


def test_duplicate_key_statistics(
    inspector: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = _minimal_files(tmp_path, duplicate_train_key=True)
    code, payload, _ = _run(
        inspector,
        files,
        capsys,
        "--train-xlsx-id-column",
        "source_id",
        "--train-json-id-field",
        "label_id",
        "--validation-xlsx-id-column",
        "source_id",
        "--validation-json-id-field",
        "label_id",
    )
    assert code == 0
    assert payload is not None
    join = payload["splits"]["train"]["join_candidates"][0]
    assert join["xlsx_duplicate_key_count"] == 1
    assert join["json_duplicate_key_count"] == 1
    assert join["relationship"] == "many_to_many_or_invalid"


def test_invalid_explicit_field_fails_without_path_or_value(
    inspector: ModuleType,
    synthetic_files: SyntheticFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload, console = _run(
        inspector,
        synthetic_files,
        capsys,
        "--train-xlsx-id-column",
        "missing_private_field",
        "--train-json-id-field",
        "label_id",
    )
    assert code == 2
    assert payload is None
    assert str(synthetic_files.train_xlsx) not in console
    for value in synthetic_files.sensitive_values:
        assert value not in console


def test_cross_split_checks_run_only_for_explicit_fields(
    inspector: ModuleType,
    synthetic_files: SyntheticFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload, _ = _run(
        inspector,
        synthetic_files,
        capsys,
        "--train-text-field",
        "xlsx:utterance_text",
        "--validation-text-field",
        "xlsx:utterance_text",
        "--train-conversation-field",
        "xlsx:conversation_id",
        "--validation-conversation-field",
        "xlsx:conversation_id",
    )
    assert code == 0
    assert payload is not None
    checks = payload["cross_split_checks"]
    assert checks["source_id_overlap"]["status"] == "not_run"
    assert checks["group_id_overlap"]["status"] == "not_run"
    assert checks["conversation_id_overlap"]["overlap_count"] == 1
    assert checks["normalized_text_overlap"]["overlap_count"] == 1


def test_empty_data_mixed_types_long_strings_and_split_separation(
    inspector: ModuleType,
    synthetic_files: SyntheticFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload, _ = _run(inspector, synthetic_files, capsys)
    assert code == 0
    assert payload is not None
    train_sheet = payload["splits"]["train"]["xlsx_schema"]["sheets"][0]
    validation_sheet = payload["splits"]["validation"]["xlsx_schema"]["sheets"][0]
    assert train_sheet["data_row_count"] == 2
    assert validation_sheet["data_row_count"] == 2
    train_columns = {column["name"]: column for column in train_sheet["columns"]}
    validation_columns = {
        column["name"]: column for column in validation_sheet["columns"]
    }
    assert train_columns["mixed_value"]["type_counts"]["integer"] == 1
    assert train_columns["mixed_value"]["type_counts"]["string"] == 1
    assert validation_columns["mixed_value"]["type_counts"]["float"] == 1
    assert validation_columns["mixed_value"]["type_counts"]["boolean"] == 1
    assert train_columns["very_long_text"]["string_length_statistics"]["max"] > 10_000

    empty_dir = synthetic_files.output.parent / "empty"
    empty_dir.mkdir()
    empty_files = _empty_files(empty_dir)
    code, empty_payload, _ = _run(inspector, empty_files, capsys)
    assert code == 0
    assert empty_payload is not None
    assert (
        empty_payload["splits"]["train"]["xlsx_schema"]["sheets"][0]["data_row_count"]
        == 0
    )
    assert empty_payload["splits"]["train"]["json_schema"]["record_count"] == 0


def _empty_files(tmp_path: Path) -> SyntheticFiles:
    train_xlsx = tmp_path / "empty_train.xlsx"
    train_json = tmp_path / "empty_train.json"
    validation_xlsx = tmp_path / "empty_validation.xlsx"
    validation_json = tmp_path / "empty_validation.json"
    _write_xlsx(train_xlsx, [], header=["source_id", "utterance_text"])
    _write_xlsx(validation_xlsx, [], header=["source_id", "utterance_text"])
    _write_json(train_json, [])
    _write_json(validation_json, [])
    return SyntheticFiles(
        train_xlsx,
        train_json,
        validation_xlsx,
        validation_json,
        tmp_path / "empty_output.json",
        (),
    )


def test_non_ascii_korean_field_names_and_json_array_object_types(
    inspector: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = _minimal_files(tmp_path)
    _write_xlsx(
        files.train_xlsx,
        [["PRIVATE-KO-ID", "PRIVATE KO TEXT"]],
        header=["원천_id", "발화문"],
    )
    _write_json(
        files.train_json,
        {
            "records": [
                {
                    "라벨_id": "PRIVATE-KO-ID",
                    "메타데이터": {"속성명": "PRIVATE META"},
                    "목록": [{"내부키": "PRIVATE INNER"}],
                }
            ]
        },
    )
    code, payload, _ = _run(inspector, files, capsys)
    assert code == 0
    assert payload is not None
    roles = payload["splits"]["train"]["role_candidates"]
    assert any(
        role["field"] == "발화문" and role["candidate_role"] == "utterance_text"
        for role in roles
    )
    fields = {
        item["path"]: item
        for item in payload["splits"]["train"]["json_schema"]["fields"]
    }
    assert fields["$.records[].메타데이터"]["type_counts"]["object"] == 1
    assert fields["$.records[].목록"]["type_counts"]["array"] == 1
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "PRIVATE-KO-ID" not in serialized
    assert "PRIVATE META" not in serialized
    assert "PRIVATE INNER" not in serialized


def test_relative_paths_are_rejected_without_echoing_them(
    inspector: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = inspector.main(
        [
            "--train-source-xlsx",
            "private-train.xlsx",
            "--train-label-json",
            "private-train.json",
            "--validation-source-xlsx",
            "private-validation.xlsx",
            "--validation-label-json",
            "private-validation.json",
            "--output",
            "private-output.json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "private-train.xlsx" not in captured.err
    assert "absolute" in captured.err


def test_date_type_is_reported(
    inspector: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = _minimal_files(tmp_path)
    _write_xlsx(
        files.train_xlsx,
        [[datetime(2026, 1, 2), "PRIVATE DATE TEXT"]],
        header=["event_date", "utterance_text"],
    )
    code, payload, _ = _run(inspector, files, capsys)
    assert code == 0
    assert payload is not None
    column = payload["splits"]["train"]["xlsx_schema"]["sheets"][0]["columns"][0]
    assert column["type_counts"]["date_or_datetime"] == 1
