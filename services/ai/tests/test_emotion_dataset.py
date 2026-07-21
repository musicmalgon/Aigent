"""Synthetic-only tests for approved emotion dataset loading."""

from __future__ import annotations

from typing import Any

import pytest

from ai.src.remind_ai.data.emotion_dataset import (
    TURN_SEPARATOR,
    DatasetValidationError,
    sample_from_record,
)


def _record(*, hs03: object = None) -> dict[str, Any]:
    return {
        "profile": {"emotion": {"type": "SYNTH_LABEL", "emotion-id": "IGNORED"}},
        "talk": {
            "content": {
                "HS01": "Synthetic first turn",
                "HS02": "Synthetic second turn",
                "HS03": hs03,
                "SS01": "PRIVATE SYSTEM RESPONSE",
                "SS02": "PRIVATE SYSTEM RESPONSE",
                "SS03": "PRIVATE SYSTEM RESPONSE",
            },
            "id": {"talk-id": "PRIVATE-TALK", "profile-id": "PRIVATE-PROFILE"},
        },
    }


def test_joins_only_hs_fields_and_omits_null_hs03() -> None:
    sample = sample_from_record(_record(hs03=None), "official_train")
    assert sample.label == "SYNTH_LABEL"
    assert (
        sample.text == "Synthetic first turn" + TURN_SEPARATOR + "Synthetic second turn"
    )
    assert "PRIVATE SYSTEM RESPONSE" not in sample.text


def test_includes_non_empty_hs03_with_turn_separator() -> None:
    sample = sample_from_record(_record(hs03="Synthetic third turn"), "official_train")
    assert sample.text.count(TURN_SEPARATOR) == 2
    assert sample.text.endswith("Synthetic third turn")


@pytest.mark.parametrize("field", ["type", "HS01", "HS02", "talk-id", "profile-id"])
def test_missing_required_fields_fail_safely(field: str) -> None:
    record = _record()
    if field == "type":
        record["profile"]["emotion"]["type"] = None
    elif field in {"HS01", "HS02"}:
        record["talk"]["content"][field] = "  "
    else:
        record["talk"]["id"][field] = None
    with pytest.raises(DatasetValidationError) as error:
        sample_from_record(record, "official_train")
    assert "PRIVATE" not in str(error.value)
