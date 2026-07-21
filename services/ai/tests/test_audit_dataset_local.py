"""Synthetic-only tests for the local emotional-dialogue audit command.

Every workbook, JSON document, identifier, group value, and sentence used here
is created under pytest's ``tmp_path``.  The real dataset path must never be
discovered or opened by this test module.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPOSITORY_ROOT / "ai" / "scripts" / "audit_dataset_local.py"


@dataclass(frozen=True)
class SyntheticAuditFiles:
    """Paths and deliberately sensitive synthetic values for one audit run."""

    train_source: Path
    train_label: Path
    validation_source: Path
    validation_label: Path
    output: Path
    sensitive_values: tuple[str, ...]

    @property
    def inputs(self) -> tuple[Path, ...]:
        return (
            self.train_source,
            self.train_label,
            self.validation_source,
            self.validation_label,
        )


def _openpyxl() -> Any:
    return pytest.importorskip(
        "openpyxl",
        reason="openpyxl is required to create synthetic XLSX fixtures",
    )


def _write_workbook(
    path: Path,
    *,
    rows: Sequence[Sequence[object]],
    header: Sequence[object] | None = None,
    extra_visible_rows: Sequence[Sequence[object]] | None = None,
    hidden_secret: str | None = None,
) -> None:
    openpyxl = _openpyxl()
    workbook = openpyxl.Workbook()
    records = workbook.active
    records.title = "Records"
    records.append(
        list(
            header
            if header is not None
            else ["source_id", "alternate_id", "group_id", "text", "score"]
        )
    )
    for row in rows:
        records.append(list(row))

    if extra_visible_rows is not None:
        alternate = workbook.create_sheet("Alternate")
        alternate.append(["source_id", "alternate_id", "group_id", "text", "score"])
        for row in extra_visible_rows:
            alternate.append(list(row))

    if hidden_secret is not None:
        hidden = workbook.create_sheet("HiddenMetadata")
        hidden.sheet_state = "hidden"
        hidden.append(["private_note"])
        hidden.append([hidden_secret])

    workbook.save(path)
    workbook.close()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_headerless_workbook(
    path: Path,
    rows: Sequence[Sequence[object]],
) -> None:
    openpyxl = _openpyxl()
    workbook = openpyxl.Workbook()
    records = workbook.active
    records.title = "Records"
    for row in rows:
        records.append(list(row))
    workbook.save(path)
    workbook.close()


def _base_source_rows() -> tuple[list[list[object]], list[list[object]]]:
    train_rows = [
        [
            "SYNTH-ID-SHARED-9001",
            "SYNTH-ALT-TRAIN-01",
            "SYNTH-GROUP-TRAIN-A",
            "SYNTHETIC TRAIN SOURCE SENTENCE ALPHA 7QX",
            1,
        ],
        [
            "SYNTH-ID-TRAIN-9002",
            "SYNTH-ALT-TRAIN-02",
            "SYNTH-GROUP-SHARED-77",
            "SYNTHETIC TRAIN SOURCE SENTENCE BETA 8QX",
            0,
        ],
        [
            "SYNTH-ID-TRAIN-9003",
            "SYNTH-ALT-TRAIN-03",
            "SYNTH-GROUP-TRAIN-C",
            "SYNTHETIC CROSS SPLIT SOURCE SENTENCE 9QX",
            None,
        ],
    ]
    validation_rows = [
        [
            "SYNTH-ID-SHARED-9001",
            "SYNTH-ALT-VALID-01",
            "SYNTH-GROUP-VALID-A",
            "SYNTHETIC VALIDATION SOURCE SENTENCE ALPHA 1VX",
            2,
        ],
        [
            "SYNTH-ID-VALID-9002",
            "SYNTH-ALT-VALID-02",
            "SYNTH-GROUP-SHARED-77",
            "SYNTHETIC VALIDATION SOURCE SENTENCE BETA 2VX",
            3,
        ],
        [
            "SYNTH-ID-VALID-9003",
            "SYNTH-ALT-VALID-03",
            "SYNTH-GROUP-VALID-C",
            "SYNTHETIC CROSS SPLIT SOURCE SENTENCE 9QX",
            4,
        ],
    ]
    return train_rows, validation_rows


def _label_records(
    rows: Sequence[Sequence[object]],
    *,
    labels: Sequence[str],
) -> list[dict[str, object]]:
    # Reverse the source order deliberately: successful pairing must use IDs.
    records: list[dict[str, object]] = []
    for row, label in reversed(list(zip(rows, labels, strict=True))):
        records.append(
            {
                "label_id": row[0],
                "alternate_id": row[1],
                "group_id": row[2],
                "emotion_label": label,
                "embedded_text": row[3],
            }
        )
    return records


@pytest.fixture
def synthetic_audit_files(tmp_path: Path) -> SyntheticAuditFiles:
    train_rows, validation_rows = _base_source_rows()
    train_source = tmp_path / "synthetic_training.xlsx"
    train_label = tmp_path / "synthetic_training.json"
    validation_source = tmp_path / "synthetic_validation.xlsx"
    validation_label = tmp_path / "synthetic_validation.json"
    hidden_secret = "SYNTHETIC HIDDEN SHEET CONTENT MUST STAY PRIVATE 4HZ"

    _write_workbook(
        train_source,
        rows=train_rows,
        extra_visible_rows=[
            [
                "SYNTH-ALTERNATE-SHEET-ID",
                "SYNTH-ALTERNATE-SHEET-ALT",
                "SYNTH-ALTERNATE-SHEET-GROUP",
                "SYNTHETIC ALTERNATE SHEET PRIVATE SENTENCE",
                5,
            ]
        ],
        hidden_secret=hidden_secret,
    )
    _write_workbook(
        validation_source,
        rows=validation_rows,
        extra_visible_rows=[
            [
                "SYNTH-ALTERNATE-SHEET-ID",
                "SYNTH-ALTERNATE-SHEET-ALT",
                "SYNTH-ALTERNATE-SHEET-GROUP",
                "SYNTHETIC ALTERNATE SHEET PRIVATE SENTENCE",
                5,
            ]
        ],
    )
    train_labels = _label_records(
        train_rows,
        labels=("category-alpha", "category-beta", "category-alpha"),
    )
    validation_labels = _label_records(
        validation_rows,
        labels=("category-gamma", "category-gamma", "category-delta"),
    )
    _write_json(train_label, train_labels)
    _write_json(validation_label, {"data": validation_labels})

    sensitive_values = tuple(
        str(value) for row in [*train_rows, *validation_rows] for value in row[:4]
    ) + (
        hidden_secret,
        "SYNTH-ALTERNATE-SHEET-ID",
        "SYNTH-ALTERNATE-SHEET-ALT",
        "SYNTH-ALTERNATE-SHEET-GROUP",
        "SYNTHETIC ALTERNATE SHEET PRIVATE SENTENCE",
    )
    return SyntheticAuditFiles(
        train_source=train_source,
        train_label=train_label,
        validation_source=validation_source,
        validation_label=validation_label,
        output=tmp_path / "private_audit_summary.json",
        sensitive_values=sensitive_values,
    )


@pytest.fixture(scope="module")
def audit_module() -> ModuleType:
    assert AUDIT_SCRIPT.is_file(), f"missing audit script: {AUDIT_SCRIPT.name}"
    spec = importlib.util.spec_from_file_location(
        "_audit_dataset_local_under_test",
        AUDIT_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cli_args(
    files: SyntheticAuditFiles,
    *,
    explicit_ids: bool = True,
    extra: Sequence[str] = (),
) -> list[str]:
    args = [
        "--train-source-xlsx",
        str(files.train_source),
        "--train-label-json",
        str(files.train_label),
        "--validation-source-xlsx",
        str(files.validation_source),
        "--validation-label-json",
        str(files.validation_label),
        "--output",
        str(files.output),
    ]
    if explicit_ids:
        args.extend(
            [
                "--source-id-field",
                "source_id",
                "--label-id-field",
                "label_id",
                "--text-field",
                "text",
                "--label-field",
                "emotion_label",
                "--group-field",
                "group_id",
            ]
        )
    args.extend(extra)
    return args


def _run_audit(
    audit_module: ModuleType,
    files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
    *,
    explicit_ids: bool = True,
    extra: Sequence[str] = (),
) -> tuple[dict[str, Any], str, str]:
    result_code = audit_module.main(
        _cli_args(files, explicit_ids=explicit_ids, extra=extra)
    )
    captured = capsys.readouterr()
    assert result_code in (None, 0)
    assert files.output.is_file()
    result = json.loads(files.output.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result, captured.out, captured.err


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _all_keys(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _all_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_keys(nested)


def _assert_private_output(
    *,
    result: Mapping[str, object],
    stdout: str,
    stderr: str,
    files: SyntheticAuditFiles,
    extra_forbidden: Iterable[str] = (),
) -> None:
    result_text = _serialized(result)
    stored_output = files.output.read_text(encoding="utf-8")
    all_surfaces = (result_text, stored_output, stdout, stderr)
    absolute_paths = tuple(
        str(path.resolve()) for path in (*files.inputs, files.output)
    )
    value_digests = tuple(
        hashlib.sha256(value.encode("utf-8")).hexdigest()
        for value in files.sensitive_values
    )
    forbidden = (
        *files.sensitive_values,
        *absolute_paths,
        *value_digests,
        *extra_forbidden,
    )

    for secret in forbidden:
        assert secret
        for surface in all_surfaces:
            assert secret not in surface
        if len(secret) >= 18:
            for fragment in (secret[:12], secret[-12:]):
                for surface in all_surfaces:
                    assert fragment not in surface
    for surface in all_surfaces:
        assert re.search(r"\b[0-9a-f]{64}\b", surface) is None


def test_required_output_shape_and_split_separation(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )

    assert {
        "audit_version",
        "generated_at",
        "dataset_display_name",
        "splits",
        "cross_split_leakage",
        "privacy_pattern_counts",
        "warnings",
        "limitations",
    } <= result.keys()
    assert result["dataset_display_name"] == "emotional-dialogue"
    generated_at = datetime.fromisoformat(result["generated_at"])
    assert generated_at.tzinfo is not None
    assert generated_at.utcoffset() is not None
    assert set(result["splits"]) == {"train", "validation"}
    for split_name in ("train", "validation"):
        assert {
            "source_xlsx_summary",
            "label_json_summary",
            "pairing_summary",
            "label_distribution",
        } <= result["splits"][split_name].keys()

    train_serialized = _serialized(result["splits"]["train"]["label_distribution"])
    validation_serialized = _serialized(
        result["splits"]["validation"]["label_distribution"]
    )
    assert "category-alpha" in train_serialized
    assert "category-gamma" not in train_serialized
    assert "category-gamma" in validation_serialized
    assert "category-alpha" not in validation_serialized


def test_cli_declares_exactly_five_required_path_arguments(
    audit_module: ModuleType,
) -> None:
    parser = audit_module._build_parser()
    required_destinations = {
        action.dest for action in parser._actions if getattr(action, "required", False)
    }
    assert required_destinations == {
        "train_source_xlsx",
        "train_label_json",
        "validation_source_xlsx",
        "validation_label_json",
        "output",
    }


def test_xlsx_read_only_summary_and_first_visible_sheet(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    summary = result["splits"]["train"]["source_xlsx_summary"]
    summary_text = _serialized(summary)

    assert summary["sheet_count"] == 3
    assert summary["selected_sheet"] == "Records"
    assert summary["row_count"] == 3
    assert summary["column_count"] == 5
    assert "Records" in summary_text
    assert "Alternate" in summary_text
    assert "HiddenMetadata" in summary_text
    assert "hidden" in summary_text.lower()
    assert "SYNTHETIC HIDDEN SHEET CONTENT" not in summary_text


def test_source_sheet_selects_one_sheet_without_combining(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
        extra=("--source-sheet", "Alternate"),
    )
    summary = result["splits"]["train"]["source_xlsx_summary"]
    assert summary["selected_sheet"] == "Alternate"
    assert summary["row_count"] == 1


def test_headerless_short_rows_are_redacted_not_exposed_as_headers(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_id = "source_id_private_9001"
    private_note = "text_private_note"
    _write_headerless_workbook(
        synthetic_audit_files.train_source,
        [
            [private_id, private_note],
            ["source_id_private_9002", "text_private_followup"],
        ],
    )

    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    summary = result["splits"]["train"]["source_xlsx_summary"]
    assert summary["header_detected"] is False
    assert summary["header_candidates"] == ["column_1", "column_2"]
    assert summary["row_count"] == 2
    for private_value in (private_id, private_note):
        assert private_value not in _serialized(result)
        assert private_value not in stdout
        assert private_value not in stderr


def test_missing_zero_types_duplicates_and_text_lengths_are_distinct(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    summary = result["splits"]["train"]["source_xlsx_summary"]
    assert summary["missing_by_field"]["score"] == 1
    assert summary["type_counts_by_field"]["score"] == {"integer": 2, "null": 1}
    assert summary["duplicate_row_count"] == 0
    assert summary["text_length_statistics"]["text"]["count"] == 3


def test_explicit_hidden_sheet_is_rejected_without_reading_its_cells(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result_code = audit_module.main(
        _cli_args(
            synthetic_audit_files,
            extra=("--source-sheet", "HiddenMetadata"),
        )
    )
    captured = capsys.readouterr()
    assert result_code == 2
    assert "SYNTHETIC HIDDEN SHEET CONTENT" not in captured.out
    assert "SYNTHETIC HIDDEN SHEET CONTENT" not in captured.err
    assert str(synthetic_audit_files.train_source.resolve()) not in captured.err


def test_json_top_level_array_and_nested_data_candidates_are_detected(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    train = result["splits"]["train"]["label_json_summary"]
    validation = result["splits"]["validation"]["label_json_summary"]

    assert train["top_level_type"] == "array"
    assert train["record_count"] == 3
    assert validation["top_level_type"] == "object"
    assert "data" in validation["top_level_keys"]
    assert "data" in _serialized(validation["record_array_candidate_paths"])
    assert validation["record_count"] == 3
    assert validation["text_field_present"] is True


def test_json_encoding_option_is_applied(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_rows, validation_rows = _base_source_rows()
    encoded_records = _label_records(
        train_rows,
        labels=("category-alpha", "category-beta", "category-alpha"),
    )
    synthetic_audit_files.train_label.write_text(
        json.dumps(encoded_records, ensure_ascii=False),
        encoding="utf-16",
    )
    synthetic_audit_files.validation_label.write_text(
        json.dumps(
            {
                "data": _label_records(
                    validation_rows,
                    labels=("category-gamma", "category-gamma", "category-delta"),
                )
            },
            ensure_ascii=False,
        ),
        encoding="utf-16",
    )
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
        extra=("--encoding", "utf-16"),
    )
    assert result["splits"]["train"]["label_json_summary"]["record_count"] == 3


@pytest.mark.parametrize(
    ("wrapper", "expected_path_fragment"),
    [
        ({"records": []}, "records"),
        ({"data": []}, "data"),
        ({"file": {"annotations": []}}, "annotations"),
        ({"files": [{"annotation": []}]}, "annotation"),
    ],
)
def test_nested_json_array_candidates_are_reported_without_flattening(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
    wrapper: dict[str, object],
    expected_path_fragment: str,
) -> None:
    _write_json(synthetic_audit_files.validation_label, wrapper)
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    summary = result["splits"]["validation"]["label_json_summary"]
    candidates = _serialized(summary["record_array_candidate_paths"])
    assert expected_path_fragment in candidates


def test_multiple_file_annotations_remain_ambiguous_and_hide_dynamic_keys(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_file_ids = ("SYNTH-PRIVATE-FILE-9001", "SYNTH-PRIVATE-FILE-9002")
    _write_json(
        synthetic_audit_files.validation_label,
        {
            file_id: {
                "annotation": {
                    "label_id": f"SYNTH-LABEL-{index}",
                    "emotion_label": "category-gamma",
                }
            }
            for index, file_id in enumerate(private_file_ids)
        },
    )

    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    summary = result["splits"]["validation"]["label_json_summary"]
    assert summary["top_level_keys"] == []
    assert summary["top_level_keys_redacted"] is True
    assert summary["selected_record_array_path"] is None
    assert summary["statistics_available"] is False
    assert summary["record_count"] is None
    pairing = result["splits"]["validation"]["pairing_summary"]
    assert pairing["matched_record_count"] is None
    assert pairing["source_only_count"] is None
    assert pairing["label_only_count"] is None
    serialized = _serialized(result)
    assert "$.*.annotation" in _serialized(summary["record_array_candidate_paths"])
    for private_file_id in private_file_ids:
        assert private_file_id not in serialized
        assert private_file_id not in stdout
        assert private_file_id not in stderr


def test_dynamic_record_keys_inside_an_array_are_redacted(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_dynamic_key = "SYNTH-PRIVATE-DYNAMIC-RECORD-ID-9001"
    _write_json(
        synthetic_audit_files.train_label,
        [{private_dynamic_key: {"emotion_label": "category-alpha"}}],
    )

    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    summary = result["splits"]["train"]["label_json_summary"]
    assert summary["field_name_candidates"] == []
    assert summary["field_names_redacted"] is True
    assert private_dynamic_key not in _serialized(result)
    assert private_dynamic_key not in stdout
    assert private_dynamic_key not in stderr


def test_explicit_id_pairing_succeeds_for_both_splits_despite_order(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    for split_name in ("train", "validation"):
        pairing = result["splits"][split_name]["pairing_summary"]
        assert pairing["selected_join_strategy"] == "explicit_id_fields"
        assert pairing["join_status"] == "complete"
        assert pairing["source_record_count"] == 3
        assert pairing["label_record_count"] == 3
        assert pairing["matched_record_count"] == 3
        assert pairing["source_only_count"] == 0
        assert pairing["label_only_count"] == 0


def test_one_unique_common_id_candidate_is_used_for_both_splits(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_rows = [
        ["SYNTH-COMMON-TRAIN-1", "SYNTHETIC COMMON TRAIN TEXT ONE"],
        ["SYNTH-COMMON-TRAIN-2", "SYNTHETIC COMMON TRAIN TEXT TWO"],
    ]
    validation_rows = [
        ["SYNTH-COMMON-VALID-1", "SYNTHETIC COMMON VALID TEXT ONE"],
        ["SYNTH-COMMON-VALID-2", "SYNTHETIC COMMON VALID TEXT TWO"],
    ]
    _write_workbook(
        synthetic_audit_files.train_source,
        header=["record_id", "text"],
        rows=train_rows,
    )
    _write_workbook(
        synthetic_audit_files.validation_source,
        header=["record_id", "text"],
        rows=validation_rows,
    )
    _write_json(
        synthetic_audit_files.train_label,
        [
            {"record_id": row[0], "emotion_label": "category-alpha"}
            for row in reversed(train_rows)
        ],
    )
    _write_json(
        synthetic_audit_files.validation_label,
        [
            {"record_id": row[0], "emotion_label": "category-gamma"}
            for row in reversed(validation_rows)
        ],
    )

    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
        explicit_ids=False,
        extra=("--text-field", "text", "--label-field", "emotion_label"),
    )
    for split_name in ("train", "validation"):
        pairing = result["splits"][split_name]["pairing_summary"]
        assert pairing["selected_join_strategy"] == "common_id_candidate"
        assert pairing["join_status"] == "complete"
        assert pairing["matched_record_count"] == 2


def test_same_row_order_with_different_ids_does_not_match(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_json(
        synthetic_audit_files.train_label,
        [
            {
                "label_id": f"SYNTH-DIFFERENT-LABEL-ID-{number}",
                "emotion_label": "category-alpha",
            }
            for number in range(3)
        ],
    )
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    pairing = result["splits"]["train"]["pairing_summary"]
    assert pairing["matched_record_count"] == 0
    assert pairing["source_only_count"] == 3
    assert pairing["label_only_count"] == 3
    assert pairing["join_status"] != "complete"


def test_source_only_and_label_only_records_are_counted(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_rows, _ = _base_source_rows()
    labels = _label_records(
        train_rows[:2],
        labels=("category-alpha", "category-beta"),
    )
    labels.append(
        {
            "label_id": "SYNTH-LABEL-ONLY-ID-404",
            "emotion_label": "category-alpha",
        }
    )
    _write_json(synthetic_audit_files.train_label, labels)

    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    pairing = result["splits"]["train"]["pairing_summary"]
    assert pairing["matched_record_count"] == 2
    assert pairing["source_only_count"] == 1
    assert pairing["label_only_count"] == 1
    assert pairing["join_status"] == "partial"


def test_duplicate_source_and_label_ids_are_counted(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    duplicate_source_rows = [
        [
            "SYNTH-DUPLICATE-SOURCE-ID",
            "SYNTH-ALT-DUP-01",
            "SYNTH-GROUP-DUP-01",
            "SYNTHETIC DUPLICATE SOURCE SENTENCE ONE",
            1,
        ],
        [
            "SYNTH-DUPLICATE-SOURCE-ID",
            "SYNTH-ALT-DUP-02",
            "SYNTH-GROUP-DUP-02",
            "SYNTHETIC DUPLICATE SOURCE SENTENCE TWO",
            2,
        ],
    ]
    _write_workbook(
        synthetic_audit_files.train_source,
        rows=duplicate_source_rows,
    )
    _write_json(
        synthetic_audit_files.train_label,
        [
            {
                "label_id": "SYNTH-DUPLICATE-SOURCE-ID",
                "emotion_label": "category-alpha",
            },
            {
                "label_id": "SYNTH-DUPLICATE-SOURCE-ID",
                "emotion_label": "category-beta",
            },
        ],
    )

    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    pairing = result["splits"]["train"]["pairing_summary"]
    assert pairing["duplicate_source_key_count"] >= 1
    assert pairing["duplicate_label_key_count"] >= 1
    assert pairing["ambiguous_match_count"] >= 1
    assert pairing["join_status"] == "invalid"
    assert result["splits"]["train"]["label_json_summary"]["duplicate_id_count"] >= 1


def test_multiple_common_id_candidates_remain_unresolved(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
        explicit_ids=False,
        extra=("--text-field", "text", "--label-field", "emotion_label"),
    )
    for split_name in ("train", "validation"):
        pairing = result["splits"][split_name]["pairing_summary"]
        assert pairing["selected_join_strategy"] == "unresolved"
        assert pairing["join_status"] == "unresolved"
        assert pairing["matched_record_count"] is None
        assert pairing["source_only_count"] is None
        assert pairing["label_only_count"] is None
        assert len(pairing["candidate_source_id_fields"]) >= 2
        assert len(pairing["candidate_label_id_fields"]) >= 2


def test_unselected_label_field_uses_null_not_false_zero_counts(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
        explicit_ids=False,
    )
    for split_name in ("train", "validation"):
        summary = result["splits"][split_name]["label_json_summary"]
        assert summary["statistics_available"] is True
        assert summary["selected_label_field"] is None
        assert summary["label_statistics_available"] is False
        assert summary["distinct_label_count"] is None
        assert summary["missing_label_count"] is None


def test_id_candidate_detection_uses_token_boundaries(
    audit_module: ModuleType,
) -> None:
    assert audit_module._id_candidates(["valid_score", "video", "grid"]) == []
    assert audit_module._id_candidates(["record_id"]) == ["record_id"]


def test_cross_split_id_group_and_text_leakage_counts_only(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    leakage = result["cross_split_leakage"]
    assert leakage["same_source_id_count"] == 1
    assert leakage["same_group_id_count"] == 1
    assert leakage["same_text_count"] == 1
    assert leakage["same_source_record_count"] == 0
    assert leakage["train_source_validation_label_id_overlap_count"] == 1
    assert leakage["validation_source_train_label_id_overlap_count"] == 1
    assert all(isinstance(value, (int, bool, type(None))) for value in leakage.values())
    _assert_private_output(
        result=result,
        stdout=stdout,
        stderr=stderr,
        files=synthetic_audit_files,
    )


def test_same_source_record_digest_is_independent_of_column_order(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shared_id = "SYNTH-ORDER-INDEPENDENT-ID"
    shared_text = "SYNTHETIC ORDER INDEPENDENT TEXT"
    _write_workbook(
        synthetic_audit_files.train_source,
        header=["source_id", "text"],
        rows=[[shared_id, shared_text]],
    )
    _write_workbook(
        synthetic_audit_files.validation_source,
        header=["text", "source_id"],
        rows=[[shared_text, shared_id]],
    )
    _write_json(
        synthetic_audit_files.train_label,
        [{"label_id": shared_id, "emotion_label": "category-alpha"}],
    )
    _write_json(
        synthetic_audit_files.validation_label,
        [{"label_id": shared_id, "emotion_label": "category-alpha"}],
    )

    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    assert result["cross_split_leakage"]["same_source_record_count"] == 1


def test_privacy_patterns_are_counted_without_exposing_matches(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_text = "contact synthetic.private@example.test or 010-1234-5678"
    train_rows, _ = _base_source_rows()
    train_rows[0][3] = private_text
    _write_workbook(synthetic_audit_files.train_source, rows=train_rows)

    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    counts = result["privacy_pattern_counts"]["train_source"]
    assert counts["email_like"] >= 1
    assert counts["phone_like"] >= 1
    assert private_text not in _serialized(result)
    assert private_text not in stdout
    assert private_text not in stderr


def test_result_file_stdout_and_stderr_never_expose_values_paths_or_digests(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    _assert_private_output(
        result=result,
        stdout=stdout,
        stderr=stderr,
        files=synthetic_audit_files,
    )


def test_input_xlsx_and_json_files_are_not_modified(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = {path: _sha256(path) for path in synthetic_audit_files.inputs}
    _run_audit(audit_module, synthetic_audit_files, capsys)
    after = {path: _sha256(path) for path in synthetic_audit_files.inputs}
    assert after == before


def test_same_input_file_cannot_be_reused_across_official_splits(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _cli_args(synthetic_audit_files)
    validation_index = args.index("--validation-source-xlsx") + 1
    args[validation_index] = str(synthetic_audit_files.train_source)
    result_code = audit_module.main(args)
    captured = capsys.readouterr()
    assert result_code == 2
    assert str(synthetic_audit_files.train_source.resolve()) not in captured.out
    assert str(synthetic_audit_files.train_source.resolve()) not in captured.err


def test_hidden_sheet_generates_content_free_warning(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    warnings = _serialized(result["warnings"])
    assert "hidden" in warnings.lower()
    assert "HiddenMetadata" in warnings
    _assert_private_output(
        result=result,
        stdout=stdout,
        stderr=stderr,
        files=synthetic_audit_files,
    )


def test_free_form_label_values_are_redacted(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    free_form_labels = [
        "SYNTHETIC PRIVATE FREE FORM LABEL SENTENCE NUMBER ONE WITH MANY WORDS",
        "SYNTHETIC PRIVATE FREE FORM LABEL SENTENCE NUMBER TWO WITH MANY WORDS",
        "SYNTHETIC PRIVATE FREE FORM LABEL SENTENCE NUMBER THREE WITH MANY WORDS",
    ]
    train_rows, _ = _base_source_rows()
    records = _label_records(train_rows, labels=free_form_labels)
    _write_json(synthetic_audit_files.train_label, records)

    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    summary = result["splits"]["train"]["label_json_summary"]
    assert summary["label_values_redacted"] is True
    assert summary["distinct_label_count"] == 3
    _assert_private_output(
        result=result,
        stdout=stdout,
        stderr=stderr,
        files=synthetic_audit_files,
        extra_forbidden=free_form_labels,
    )


def test_missing_labels_are_counted_separately(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_rows, _ = _base_source_rows()
    records = _label_records(
        train_rows,
        labels=("category-alpha", "category-alpha", "category-beta"),
    )
    records[0].pop("emotion_label")
    _write_json(synthetic_audit_files.train_label, records)

    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    summary = result["splits"]["train"]["label_json_summary"]
    assert summary["missing_label_count"] == 1
    assert summary["missing_by_field"]["emotion_label"] == 1


def test_short_sentence_like_labels_are_redacted(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    short_private_labels = [
        "felt sad today",
        "angry after work",
        "felt sad today",
    ]
    train_rows, _ = _base_source_rows()
    _write_json(
        synthetic_audit_files.train_label,
        _label_records(train_rows, labels=short_private_labels),
    )

    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    summary = result["splits"]["train"]["label_json_summary"]
    assert summary["label_values_redacted"] is True
    assert result["splits"]["train"]["label_distribution"] == {}
    _assert_private_output(
        result=result,
        stdout=stdout,
        stderr=stderr,
        files=synthetic_audit_files,
        extra_forbidden=short_private_labels,
    )


def test_repeated_person_names_are_not_treated_as_safe_categories(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_names = ("김민수", "김민수", "이영희")
    train_rows, _ = _base_source_rows()
    _write_json(
        synthetic_audit_files.train_label,
        [
            {"label_id": row[0], "person_name": name}
            for row, name in zip(train_rows, private_names, strict=True)
        ],
    )

    result, stdout, stderr = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
        extra=("--label-field", "person_name"),
    )
    summary = result["splits"]["train"]["label_json_summary"]
    assert summary["label_values_redacted"] is True
    assert result["splits"]["train"]["label_distribution"] == {}
    _assert_private_output(
        result=result,
        stdout=stdout,
        stderr=stderr,
        files=synthetic_audit_files,
        extra_forbidden=private_names,
    )


def test_short_categorical_labels_are_counted_without_automatic_mapping(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
    )
    distribution = _serialized(result["splits"]["train"]["label_distribution"])
    assert "category-alpha" in distribution
    assert "category-beta" in distribution
    forbidden_mapping_keys = {
        "canonical_label",
        "mapped_label",
        "remind_label",
        "label_mapping",
    }
    assert forbidden_mapping_keys.isdisjoint(set(_all_keys(result)))


def test_auto_detected_label_field_keeps_string_values_redacted(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train_rows = [
        ["SYNTH-AUTO-LABEL-1", "SYNTHETIC AUTO LABEL TEXT ONE"],
        ["SYNTH-AUTO-LABEL-2", "SYNTHETIC AUTO LABEL TEXT TWO"],
    ]
    validation_rows = [
        ["SYNTH-AUTO-LABEL-3", "SYNTHETIC AUTO LABEL TEXT THREE"],
        ["SYNTH-AUTO-LABEL-4", "SYNTHETIC AUTO LABEL TEXT FOUR"],
    ]
    _write_workbook(
        synthetic_audit_files.train_source,
        header=["record_id", "text"],
        rows=train_rows,
    )
    _write_workbook(
        synthetic_audit_files.validation_source,
        header=["record_id", "text"],
        rows=validation_rows,
    )
    _write_json(
        synthetic_audit_files.train_label,
        [{"record_id": row[0], "emotion": "private-category"} for row in train_rows],
    )
    _write_json(
        synthetic_audit_files.validation_label,
        [
            {"record_id": row[0], "emotion": "private-category"}
            for row in validation_rows
        ],
    )

    result, _, _ = _run_audit(
        audit_module,
        synthetic_audit_files,
        capsys,
        explicit_ids=False,
        extra=("--text-field", "text"),
    )
    for split_name in ("train", "validation"):
        split = result["splits"][split_name]
        assert split["label_json_summary"]["selected_label_field"] == "emotion"
        assert split["label_json_summary"]["label_values_redacted"] is True
        assert split["label_distribution"] == {}


def test_failures_do_not_echo_absolute_input_paths(
    audit_module: ModuleType,
    synthetic_audit_files: SyntheticAuditFiles,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_path = (
        tmp_path
        / "SYNTHETIC-PRIVATE-MISSING-DIRECTORY"
        / "SYNTHETIC-PRIVATE-MISSING.xlsx"
    )
    args = _cli_args(synthetic_audit_files)
    args[args.index(str(synthetic_audit_files.train_source))] = str(missing_path)
    exception_text = ""
    try:
        result_code = audit_module.main(args)
        assert result_code not in (None, 0)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - verifies sanitization
        exception_text = str(exc)

    captured = capsys.readouterr()
    surfaces = (captured.out, captured.err, exception_text)
    assert all(str(missing_path.resolve()) not in surface for surface in surfaces)


def test_malformed_cli_does_not_echo_an_absolute_argument(
    audit_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_argument = str((tmp_path / "SYNTH-PRIVATE-ARGUMENT.xlsx").resolve())
    result_code = audit_module.main([private_argument])
    captured = capsys.readouterr()
    assert result_code == 2
    assert private_argument not in captured.out
    assert private_argument not in captured.err


def test_audit_script_contains_no_network_or_shell_escape_capability() -> None:
    source = AUDIT_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_import_roots = {
        "aiohttp",
        "ftplib",
        "http",
        "httpx",
        "requests",
        "shutil",
        "sklearn",
        "socket",
        "subprocess",
        "torch",
        "transformers",
        "urllib",
        "websocket",
    }
    forbidden_calls = {
        "create_connection",
        "popen",
        "system",
        "urlopen",
        "urlretrieve",
    }

    imported_roots: set[str] = set()
    called_names: set[str] = set()
    string_literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.partition(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_literals.append(node.value)

    assert imported_roots.isdisjoint(forbidden_import_roots)
    assert called_names.isdisjoint(forbidden_calls)
    assert not any(
        protocol in literal.lower()
        for literal in string_literals
        for protocol in ("http://", "https://", "ftp://")
    )


def test_openpyxl_is_loaded_in_read_only_data_only_mode_without_saving() -> None:
    source = AUDIT_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    load_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "load_workbook")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "load_workbook"
            )
        )
    ]
    assert load_calls
    for call in load_calls:
        keyword_values = {
            keyword.arg: keyword.value
            for keyword in call.keywords
            if keyword.arg is not None
        }
        for required_keyword in ("read_only", "data_only"):
            value = keyword_values[required_keyword]
            assert isinstance(value, ast.Constant)
            assert value.value is True
        if "keep_links" in keyword_values:
            keep_links = keyword_values["keep_links"]
            assert isinstance(keep_links, ast.Constant)
            assert keep_links.value is False

    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "save" not in called_attributes
