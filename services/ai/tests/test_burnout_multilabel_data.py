from __future__ import annotations

import json

import pytest
from ai.src.remind_ai.data.burnout_multilabel import (
    BURNOUT_SIGNAL_VALUES,
    BurnoutMultilabelDataError,
    BurnoutMultilabelSample,
    calibrate_thresholds,
    load_burnout_multilabel_jsonl,
    validate_split_isolation,
    weighted_positive_class_weights,
)


def _row(candidate_id: str, role: str, *, masked: bool = False) -> dict[str, object]:
    return {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "dataset_role": role,
        "text": f"text {candidate_id}",
        "text_sha256": "0" * 64,
        "group_id": f"group-{candidate_id}",
        "normalized_text_cluster_id": f"cluster-{candidate_id}",
        "labels": {label: (None if masked and index == 0 else int(index % 2 == 0)) for index, label in enumerate(BURNOUT_SIGNAL_VALUES)},
        "label_mask": {label: (0 if masked and index == 0 else 1) for index, label in enumerate(BURNOUT_SIGNAL_VALUES)},
        "sample_weight": 0.1 if masked else 1.0,
    }


def test_loads_partial_training_and_full_validation(tmp_path) -> None:
    train_path = tmp_path / "train.jsonl"
    validation_path = tmp_path / "validation.jsonl"
    train_path.write_text(json.dumps(_row("train", "weak_unanimous_negative_train", masked=True)) + "\n", encoding="utf-8")
    validation_path.write_text(json.dumps(_row("validation", "independent_human_validation")) + "\n", encoding="utf-8")
    train = load_burnout_multilabel_jsonl(train_path)
    validation = load_burnout_multilabel_jsonl(validation_path, validation=True)
    assert train[0].label_mask == (0.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    assert validation[0].label_mask == (1.0,) * 6
    validate_split_isolation(train, validation)


def test_masked_label_cannot_carry_a_value(tmp_path) -> None:
    row = _row("bad", "weak_unanimous_negative_train", masked=True)
    row["labels"][BURNOUT_SIGNAL_VALUES[0]] = 0
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(BurnoutMultilabelDataError, match="masked labels"):
        load_burnout_multilabel_jsonl(path)


def test_split_isolation_checks_cluster_and_candidate() -> None:
    sample = BurnoutMultilabelSample("same", "text", (0.0,) * 6, (1.0,) * 6, 1.0, "human_gold_train", "group", "cluster")
    with pytest.raises(BurnoutMultilabelDataError, match="candidate leakage"):
        validate_split_isolation([sample], [sample])


def test_weighted_positive_weights_use_observed_cells() -> None:
    negative = BurnoutMultilabelSample("n", "n", (0.0,) * 6, (1.0,) * 6, 0.1, "weak_unanimous_negative_train", "n", "n")
    positive = BurnoutMultilabelSample("p", "p", (1.0,) * 6, (1.0,) * 6, 1.0, "human_gold_train", "p", "p")
    assert weighted_positive_class_weights([negative, positive]) == (1.0,) * 6


def test_threshold_calibration_blocks_labels_without_safe_precision() -> None:
    targets = [[1, 0, 1, 0, 1, 0] for _ in range(5)] + [[0, 1, 0, 1, 0, 1] for _ in range(5)]
    safe = [[0.9 if value else 0.1 for value in row] for row in targets]
    result = calibrate_thresholds(safe, targets, minimum_precision=0.8, minimum_positive_support=5)
    assert result["status"] == "validated"
    assert all(item["status"] == "validated" for item in result["labels"].values())
    blocked = calibrate_thresholds([[0.5] * 6 for _ in targets], targets, minimum_precision=1.0, minimum_positive_support=5)
    assert blocked["status"] == "shadow_only"
