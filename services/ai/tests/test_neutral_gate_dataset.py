from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai.src.remind_ai.data.neutral_gate_dataset import (
    NeutralGateDatasetError,
    balanced_emotional_samples,
    load_neutral_gate_dataset,
)
from ai.src.remind_ai.data.emotion_dataset import EmotionSample

REGRESSION_FIXTURE = (
    Path(__file__).parents[1]
    / "data"
    / "evaluation"
    / "neutral_gate_regression_v1.jsonl"
)


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for split in ("train", "validation", "calibration", "test"):
        for label in ("neutral", "emotional"):
            rows.append(
                {
                    "id": f"{split}-{label}",
                    "group_id": f"{split}-{label}-group",
                    "split": split,
                    "label": label,
                    "turns": [f"{split} {label} first", f"{split} {label} second"],
                }
            )
    return rows


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_dataset_contract_and_summary(tmp_path: Path) -> None:
    path = tmp_path / "gate.jsonl"
    _write(path, _rows())
    dataset = load_neutral_gate_dataset(path)
    assert set(dataset.samples_by_split) == {
        "train",
        "validation",
        "calibration",
        "test",
    }
    assert dataset.summary["sample_count"] == 8
    assert dataset.summary["group_overlap_count"] == 0


def test_group_and_text_leakage_are_rejected(tmp_path: Path) -> None:
    rows = _rows()
    rows[2]["group_id"] = rows[0]["group_id"]
    path = tmp_path / "group-leak.jsonl"
    _write(path, rows)
    with pytest.raises(NeutralGateDatasetError, match="group appears"):
        load_neutral_gate_dataset(path)

    rows = _rows()
    rows[2]["turns"] = rows[0]["turns"]
    path = tmp_path / "text-leak.jsonl"
    _write(path, rows)
    with pytest.raises(NeutralGateDatasetError, match="duplicate text"):
        load_neutral_gate_dataset(path)


def test_existing_six_class_samples_are_balanced_and_relabelled() -> None:
    samples = [
        EmotionSample(
            text=f"{label} example {index}",
            label=label,
            sample_id=f"{label}-{index}",
            group_id=f"{label}-group-{index}",
            official_split="train",
        )
        for label in ("분노", "기쁨", "불안", "당황", "슬픔", "무기력")
        for index in range(3)
    ]
    first = balanced_emotional_samples(
        samples,
        per_class=2,
        random_state=777,
        split="train",
    )
    second = balanced_emotional_samples(
        samples,
        per_class=2,
        random_state=777,
        split="train",
    )
    assert first == second
    assert len(first) == 12
    assert {sample.label for sample in first} == {"emotional"}
    assert {sample.official_split for sample in first} == {"train"}


def test_deployment_neutral_false_positive_is_in_regression_fixture() -> None:
    rows = [
        json.loads(line)
        for line in REGRESSION_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[0] == {
        "id": "neutral-regression-001",
        "label": "neutral",
        "turns": [
            "오늘 오전에 수업에 갔어.",
            "점심을 먹고 도서관에서 과제를 마쳤어.",
            "저녁에는 집에 돌아왔어.",
        ],
    }
