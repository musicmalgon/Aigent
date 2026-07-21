"""Synthetic-only tests for the local emotion label audit."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "ai" / "scripts" / "audit_emotion_labels_local.py"


@dataclass(frozen=True)
class SyntheticFiles:
    train_json: Path
    validation_json: Path
    output: Path
    sensitive_values: tuple[str, ...]


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _record(
    *,
    emotion_type: str | None,
    emotion_id: str | None,
    situation: object,
    hs01: object,
    hs02: object = None,
    hs03: object = None,
    talk_id: object = "PRIVATE-TALK-ID",
    profile_id: object = "PRIVATE-PROFILE-ID",
) -> dict[str, object]:
    return {
        "profile": {
            "emotion": {
                "type": emotion_type,
                "emotion-id": emotion_id,
                "situation": situation,
            }
        },
        "talk": {
            "content": {
                "HS01": hs01,
                "HS02": hs02,
                "HS03": hs03,
                "SS01": "PRIVATE-SYSTEM-RESPONSE-ONE",
                "SS02": "PRIVATE-SYSTEM-RESPONSE-TWO",
                "SS03": None,
            },
            "id": {"talk-id": talk_id, "profile-id": profile_id},
        },
    }


@pytest.fixture(scope="module")
def audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_emotion_label_audit_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def synthetic_files(tmp_path: Path) -> SyntheticFiles:
    train = [
        _record(
            emotion_type="SYNTH_LABEL_A",
            emotion_id="SYNTH_DETAIL_1",
            situation=["SYNTH_SITUATION_A", "SYNTH_SITUATION_B"],
            hs01="PRIVATE USER TEXT ALPHA",
            hs02="PRIVATE USER TEXT BETA",
            hs03=None,
            talk_id="PRIVATE-TALK-DUPLICATE",
            profile_id="PRIVATE-PROFILE-SHARED",
        ),
        _record(
            emotion_type="SYNTH_LABEL_B",
            emotion_id="SYNTH_DETAIL_2",
            situation=["SYNTH_SITUATION_A"],
            hs01="PRIVATE USER TEXT GAMMA",
            hs03="PRIVATE USER TEXT DELTA",
            talk_id="PRIVATE-TALK-DUPLICATE",
            profile_id="PRIVATE-PROFILE-TRAIN-ONLY",
        ),
    ]
    validation = [
        _record(
            emotion_type="SYNTH_LABEL_VALID_ONLY",
            emotion_id="SYNTH_DETAIL_VALID_ONLY",
            situation=["SYNTH_SITUATION_B"],
            hs01="PRIVATE USER TEXT ALPHA",
            hs02="PRIVATE USER TEXT BETA",
            hs03=None,
            talk_id="PRIVATE-TALK-VALID-ONE",
            profile_id="PRIVATE-PROFILE-SHARED",
        ),
        _record(
            emotion_type=None,
            emotion_id=None,
            situation=None,
            hs01=" private user text gamma ",
            hs03="PRIVATE USER TEXT DELTA ",
            talk_id="PRIVATE-TALK-VALID-TWO",
            profile_id="PRIVATE-PROFILE-VALID-ONLY",
        ),
    ]
    train_json = tmp_path / "private_train.json"
    validation_json = tmp_path / "private_validation.json"
    _write_json(train_json, train)
    _write_json(validation_json, validation)
    return SyntheticFiles(
        train_json=train_json,
        validation_json=validation_json,
        output=tmp_path / "audit.json",
        sensitive_values=(
            "PRIVATE USER TEXT ALPHA",
            "PRIVATE USER TEXT BETA",
            "PRIVATE USER TEXT GAMMA",
            "PRIVATE USER TEXT DELTA",
            "PRIVATE-SYSTEM-RESPONSE-ONE",
            "PRIVATE-SYSTEM-RESPONSE-TWO",
            "PRIVATE-TALK-DUPLICATE",
            "PRIVATE-TALK-VALID-ONE",
            "PRIVATE-TALK-VALID-TWO",
            "PRIVATE-PROFILE-SHARED",
            "PRIVATE-PROFILE-TRAIN-ONLY",
            "PRIVATE-PROFILE-VALID-ONLY",
        ),
    )


def _run(
    audit_module: ModuleType,
    files: SyntheticFiles,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, Any] | None, str]:
    code = audit_module.main(
        [
            "--train-json",
            str(files.train_json),
            "--validation-json",
            str(files.validation_json),
            "--output",
            str(files.output),
        ]
    )
    captured = capsys.readouterr()
    payload = (
        json.loads(files.output.read_text(encoding="utf-8"))
        if files.output.exists()
        else None
    )
    return code, payload, captured.out + captured.err


def test_label_situation_utterance_and_id_aggregates(
    audit_module: ModuleType,
    synthetic_files: SyntheticFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload, _ = _run(audit_module, synthetic_files, capsys)
    assert code == 0
    assert payload is not None
    train = payload["splits"]["train"]
    assert train["record_count"] == 2
    distribution = train["emotion_type_distribution"]
    assert distribution["class_count"] == 2
    assert distribution["class_frequencies"] == {
        "SYNTH_LABEL_A": 1,
        "SYNTH_LABEL_B": 1,
    }
    assert distribution["class_ratios"]["SYNTH_LABEL_A"] == 0.5
    assert train["emotion_id_distribution"]["class_count"] == 2
    situation = train["situation_distribution"]
    assert situation["array_length_statistics"]["max"] == 2
    assert situation["item_frequencies"]["SYNTH_SITUATION_A"] == 2
    utterance = train["utterance_statistics"]
    assert utterance["fields"]["$.talk.content.HS03"]["null_count"] == 1
    assert utterance["joined_sample_count"] == 2
    assert utterance["empty_text_count"] == 0
    assert (
        train["system_response_statistics"]["fields"]["$.talk.content.SS03"][
            "null_count"
        ]
        == 2
    )
    identifiers = train["id_statistics"]
    assert identifiers["talk_id_unique_count"] == 1
    assert identifiers["duplicate_talk_id_count"] == 1
    assert identifiers["profile_talk_statistics"]["talks_per_profile"]["max"] == 1


def test_cross_split_leakage_labels_and_privacy(
    audit_module: ModuleType,
    synthetic_files: SyntheticFiles,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload, console = _run(audit_module, synthetic_files, capsys)
    assert code == 0
    assert payload is not None
    leakage = payload["cross_split_leakage"]
    assert leakage["same_talk_id"]["overlap_count"] == 0
    assert leakage["same_profile_id"]["overlap_count"] == 1
    assert leakage["exact_user_text"]["overlap_count"] == 1
    assert leakage["normalized_user_text"]["overlap_count"] == 2
    assert leakage["same_normalized_text_different_label_conflict_count"] == 2
    assert leakage["emotion_type_class_set_difference"]["train_only"] == [
        "SYNTH_LABEL_A",
        "SYNTH_LABEL_B",
    ]
    assert leakage["emotion_type_class_set_difference"]["validation_only"] == [
        "SYNTH_LABEL_VALID_ONLY"
    ]
    assert payload["recommended_label_options"][0]["approved"] is False

    serialized = json.dumps(payload, ensure_ascii=False)
    combined = serialized + console
    for value in synthetic_files.sensitive_values:
        assert value not in combined
    for path in (synthetic_files.train_json, synthetic_files.validation_json):
        assert str(path) not in combined
    assert payload["safe_output_policy"]["hashes_or_digests_serialized"] is False
    assert re.search(r"\b[0-9a-fA-F]{64}\b", serialized) is None


def test_empty_data_is_reported_without_confusing_it_with_zero(
    audit_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = SyntheticFiles(
        train_json=tmp_path / "empty_train.json",
        validation_json=tmp_path / "empty_validation.json",
        output=tmp_path / "empty_audit.json",
        sensitive_values=(),
    )
    _write_json(files.train_json, [])
    _write_json(files.validation_json, [])
    code, payload, _ = _run(audit_module, files, capsys)
    assert code == 0
    assert payload is not None
    assert payload["splits"]["train"]["record_count"] == 0
    assert payload["splits"]["train"]["emotion_type_distribution"]["class_count"] == 0
    assert (
        payload["splits"]["train"]["utterance_statistics"]["joined_sample_count"] == 0
    )


def test_invalid_root_structure_fails_without_values_or_paths(
    audit_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = SyntheticFiles(
        train_json=tmp_path / "private_invalid.json",
        validation_json=tmp_path / "private_valid.json",
        output=tmp_path / "private_output.json",
        sensitive_values=("PRIVATE-INVALID-VALUE",),
    )
    _write_json(files.train_json, {"private": "PRIVATE-INVALID-VALUE"})
    _write_json(files.validation_json, [])
    code, payload, console = _run(audit_module, files, capsys)
    assert code == 2
    assert payload is None
    assert str(files.train_json) not in console
    assert "PRIVATE-INVALID-VALUE" not in console


def test_relative_paths_are_rejected_without_echoing_them(
    audit_module: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = audit_module.main(
        [
            "--train-json",
            "private_train.json",
            "--validation-json",
            "private_validation.json",
            "--output",
            "private_output.json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "private_train.json" not in captured.err
    assert "absolute" in captured.err
