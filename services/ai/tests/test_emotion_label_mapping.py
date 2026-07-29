"""Tests for the audited AI Hub fine-to-coarse label artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai.src.emotion.base import ModelLoadError
from ai.src.emotion.coarse_transformer import (
    resolve_coarse_artifacts,
    validate_coarse_artifact_metadata,
)
from ai.src.remind_ai.data.emotion_dataset import EmotionSample
from ai.src.remind_ai.data.emotion_label_mapping import (
    EXPECTED_COARSE_LABELS,
    EXPECTED_FINE_LABELS,
    EmotionLabelMappingError,
    load_emotion_label_mapping,
    map_samples_to_coarse,
    mapping_validation_report,
)

MAPPING_PATH = Path(__file__).resolve().parents[1] / "config" / "emotion_label_mapping.json"


def _sample(label: str, index: int = 0) -> EmotionSample:
    return EmotionSample("text", label, f"talk-{index}", f"profile-{index}", "synthetic")


def test_official_mapping_covers_all_sixty_labels_exactly_once() -> None:
    mapping = load_emotion_label_mapping(MAPPING_PATH)
    assert tuple(mapping.fine_to_coarse) == EXPECTED_FINE_LABELS
    assert len(mapping.coarse_labels) == 6
    assert mapping.coarse_labels == EXPECTED_COARSE_LABELS
    assert {value.coarse_name for value in mapping.fine_to_coarse.values()} == set(
        mapping.coarse_labels
    )
    assert all(
        sum(value.coarse_name == coarse for value in mapping.fine_to_coarse.values()) == 10
        for coarse in mapping.coarse_labels
    )


def test_mapping_preserves_every_sample_and_builds_distribution_report() -> None:
    mapping = load_emotion_label_mapping(MAPPING_PATH)
    samples = [_sample(label, index) for index, label in enumerate(EXPECTED_FINE_LABELS)]
    mapped = map_samples_to_coarse(samples, mapping, mapping_path=MAPPING_PATH)
    assert len(mapped) == len(samples)
    report = mapping_validation_report(mapping, samples, {"train": mapped})
    assert report["fine_label_count"] == 60
    assert report["coarse_label_count"] == 6
    assert report["sample_count_preserved"] is True
    assert set(report["split_class_distribution"]["train"]) == set(mapping.coarse_labels)


def test_unknown_label_error_has_required_coverage_context() -> None:
    mapping = load_emotion_label_mapping(MAPPING_PATH)
    with pytest.raises(EmotionLabelMappingError) as captured:
        map_samples_to_coarse([_sample("E99")], mapping, mapping_path=MAPPING_PATH)
    message = str(captured.value)
    assert "unknown fine label 'E99'" in message
    assert "sample count=1" in message
    assert "profile-0" not in message
    assert str(MAPPING_PATH) not in message
    assert "map_samples_to_coarse" in message


def test_invalid_mapping_file_fails_before_training(tmp_path: Path) -> None:
    payload = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    payload["fine_to_coarse"].pop("E69")
    invalid = tmp_path / "mapping.json"
    invalid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(EmotionLabelMappingError, match="coverage"):
        load_emotion_label_mapping(invalid)


def test_v1_training_metadata_is_rejected_by_the_v2_inference_loader(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "coarse-artifact"
    model_dir = artifact / "model"
    tokenizer_dir = artifact / "tokenizer"
    model_dir.mkdir(parents=True)
    tokenizer_dir.mkdir()
    labels = EXPECTED_COARSE_LABELS
    (model_dir / "config.json").write_text(
        json.dumps(
            {
                "num_labels": 6,
                "id2label": {
                    str(index): label for index, label in enumerate(labels)
                },
                "label2id": {
                    label: index for index, label in enumerate(labels)
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (model_dir / "model.safetensors").touch()
    (tokenizer_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    (artifact / "label_mapping.json").write_text(
        MAPPING_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (artifact / "run_config.json").write_text(
        json.dumps(
            {"label_level": "coarse", "num_labels": 6, "max_length": 128}
        ),
        encoding="utf-8",
    )

    paths = resolve_coarse_artifacts(artifact_dir=artifact)
    with pytest.raises(ModelLoadError, match="label order"):
        validate_coarse_artifact_metadata(paths)
