"""Unit tests for coarse artifact loading and six-class inference."""

from __future__ import annotations

from contextlib import nullcontext
import json
import logging
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from ai.src.emotion.base import (
    ModelLoadError,
    PredictionExecutionError,
    PredictionOutputError,
)
from ai.src.emotion.coarse_settings import CoarseEmotionSettings
from ai.src.emotion.coarse_transformer import (
    EXPECTED_ID2LABEL,
    EXPECTED_LABEL2ID,
    CoarseTransformerEmotionAnalyzer,
    classify_uncertainty,
    resolve_coarse_artifacts,
    select_inference_device,
    validate_coarse_artifact_metadata,
)
from ai.src.schemas import CoarseEmotionInput, UncertaintyReason


def _write_model(directory: Path, *, labels: list[str] | None = None) -> None:
    directory.mkdir(parents=True)
    selected = labels or list(EXPECTED_LABEL2ID)
    config = {
        "num_labels": len(selected),
        "id2label": {str(index): label for index, label in enumerate(selected)},
        "label2id": {label: index for index, label in enumerate(selected)},
    }
    (directory / "config.json").write_text(
        json.dumps(config, ensure_ascii=False), encoding="utf-8"
    )
    (directory / "model.safetensors").touch()


def _write_tokenizer(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tokenizer.json").write_text("{}", encoding="utf-8")


def _separate_artifact(root: Path) -> Path:
    _write_model(root / "model")
    _write_tokenizer(root / "tokenizer")
    (root / "label_mapping.json").write_text(
        json.dumps({"coarse_labels": list(EXPECTED_LABEL2ID)}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "run_config.json").write_text(
        json.dumps({"label_level": "coarse", "num_labels": 6}),
        encoding="utf-8",
    )
    return root


class _FakeTensor:
    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = rows

    def to(self, device: object) -> "_FakeTensor":
        del device
        return self

    def detach(self) -> "_FakeTensor":
        return self

    def cpu(self) -> "_FakeTensor":
        return self

    def tolist(self) -> list[list[float]]:
        return self.rows


class _FakeCuda:
    def __init__(self, available: bool = False) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available


class _FakeMps:
    def __init__(self, available: bool = False) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available


class _FakeTorch:
    def __init__(self, *, cuda: bool = False, mps: bool = False) -> None:
        self.cuda = _FakeCuda(cuda)
        self.backends = SimpleNamespace(mps=_FakeMps(mps))

    @staticmethod
    def device(name: str) -> str:
        return name

    @staticmethod
    def inference_mode() -> Any:
        return nullcontext()

    @staticmethod
    def softmax(logits: _FakeTensor, dim: int) -> _FakeTensor:
        assert dim == -1
        rows = []
        for row in logits.rows:
            maximum = max(row)
            exponentials = [math.exp(value - maximum) for value in row]
            total = sum(exponentials)
            rows.append([value / total for value in exponentials])
        return _FakeTensor(rows)


class _FakeTokenizer:
    sep_token = "[SEP]"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, texts: list[str], **kwargs: object) -> dict[str, _FakeTensor]:
        self.calls.append((texts, kwargs))
        rows = [[1.0, 2.0]] * len(texts)
        return {
            "input_ids": _FakeTensor(rows),
            "attention_mask": _FakeTensor(rows),
        }


class _FakeModel:
    config = SimpleNamespace(
        num_labels=6,
        id2label=EXPECTED_ID2LABEL,
        label2id=EXPECTED_LABEL2ID,
    )

    def __init__(
        self, *, fail_oom: bool = False, invalid_output: bool = False
    ) -> None:
        self.fail_oom = fail_oom
        self.invalid_output = invalid_output
        self.call_count = 0
        self.eval_count = 0
        self.device: object | None = None
        self.last_input_names: set[str] = set()

    def eval(self) -> None:
        self.eval_count += 1

    def to(self, device: object) -> None:
        self.device = device

    def __call__(self, **values: _FakeTensor) -> object:
        self.call_count += 1
        self.last_input_names = set(values)
        if self.fail_oom:
            raise RuntimeError("CUDA out of memory")
        batch_size = len(values["input_ids"].rows)
        if self.invalid_output:
            return SimpleNamespace(
                logits=_FakeTensor([[math.nan] * 6] * batch_size)
            )
        return SimpleNamespace(
            logits=_FakeTensor([[0.1, 2.0, 0.7, 0.3, 0.6, 0.2]] * batch_size)
        )


def _dependencies(
    tokenizer: _FakeTokenizer, model: _FakeModel
) -> tuple[_FakeTorch, object]:
    tokenizer_loader = SimpleNamespace(
        from_pretrained=lambda path, local_files_only: tokenizer
    )
    model_loader = SimpleNamespace(from_pretrained=lambda path, local_files_only: model)
    return _FakeTorch(), SimpleNamespace(
        AutoTokenizer=tokenizer_loader,
        AutoModelForSequenceClassification=model_loader,
    )


def test_resolves_split_and_best_checkpoint_artifact_layouts(tmp_path: Path) -> None:
    separate = _separate_artifact(tmp_path / "split artifact")
    paths = resolve_coarse_artifacts(artifact_dir=separate)
    assert paths.model_dir == separate / "model"
    assert paths.tokenizer_dir == separate / "tokenizer"
    validate_coarse_artifact_metadata(paths)

    combined = tmp_path / "combined" / "checkpoints" / "best"
    _write_model(combined)
    _write_tokenizer(combined)
    combined_paths = resolve_coarse_artifacts(artifact_dir=tmp_path / "combined")
    assert combined_paths.model_dir == combined
    assert combined_paths.tokenizer_dir == combined
    validate_coarse_artifact_metadata(combined_paths)


def test_explicit_model_and_tokenizer_directories_are_supported(tmp_path: Path) -> None:
    model = tmp_path / "windows model"
    tokenizer = tmp_path / "linux-tokenizer"
    _write_model(model)
    _write_tokenizer(tokenizer)
    paths = resolve_coarse_artifacts(model_dir=model, tokenizer_dir=tokenizer)
    assert paths.model_dir == model
    assert paths.tokenizer_dir == tokenizer


@pytest.mark.parametrize(
    "labels",
    [
        [f"E{index}" for index in range(10, 70)],
        ["불안", "기쁨", "당황", "분노", "슬픔", "상처"],
    ],
)
def test_rejects_fine_or_misordered_model_metadata(
    tmp_path: Path, labels: list[str]
) -> None:
    model = tmp_path / "model"
    _write_model(model, labels=labels)
    _write_tokenizer(model)
    paths = resolve_coarse_artifacts(model_dir=model)
    with pytest.raises(ModelLoadError):
        validate_coarse_artifact_metadata(paths)


def test_predict_returns_six_probabilities_and_loads_only_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    artifact = _separate_artifact(tmp_path / "artifact")
    tokenizer = _FakeTokenizer()
    model = _FakeModel()
    analyzer = CoarseTransformerEmotionAnalyzer(
        CoarseEmotionSettings(artifact_dir=artifact, device="cpu")
    )
    dependencies = _dependencies(tokenizer, model)
    private_text = "합성 입력은 로그에 남지 않는다"
    with patch.object(analyzer, "_import_dependencies", return_value=dependencies):
        analyzer.load()
        analyzer.load()
        with caplog.at_level(logging.INFO):
            responses = analyzer.predict_batch(
                [
                    CoarseEmotionInput(hs01=private_text, hs02="두 번째 발화"),
                    CoarseEmotionInput(hs01="다른 합성 발화", hs02="마지막 발화"),
                ]
            )

    assert analyzer.load_count == 1
    assert model.eval_count == 1
    assert model.call_count == 1
    assert model.last_input_names == {"input_ids", "attention_mask"}
    assert len(responses) == 2
    assert all(len(response.probabilities) == 6 for response in responses)
    assert all(sum(response.probabilities.values()) == pytest.approx(1.0) for response in responses)
    assert all(response.predicted_label_id == 1 for response in responses)
    assert all(
        response.top_predictions == sorted(
            response.top_predictions,
            key=lambda item: item.probability,
            reverse=True,
        )
        for response in responses
    )
    texts, options = tokenizer.calls[0]
    assert "[SEP]" in texts[0]
    assert options["truncation"] is True
    assert options["max_length"] == 128
    assert options["padding"] is True
    assert private_text not in caplog.text


def test_uncertainty_policies_cover_confidence_and_margin() -> None:
    assert classify_uncertainty(
        [0.20, 0.30, 0.15, 0.15, 0.10, 0.10],
        confidence_threshold=0.45,
        margin_threshold=0.10,
    ) is UncertaintyReason.LOW_CONFIDENCE_AND_SMALL_MARGIN
    assert classify_uncertainty(
        [0.50, 0.42, 0.02, 0.02, 0.02, 0.02],
        confidence_threshold=0.45,
        margin_threshold=0.10,
    ) is UncertaintyReason.SMALL_MARGIN
    assert classify_uncertainty(
        [0.44, 0.20, 0.10, 0.10, 0.08, 0.08],
        confidence_threshold=0.45,
        margin_threshold=0.10,
    ) is UncertaintyReason.LOW_CONFIDENCE


def test_device_selection_requires_explicit_accelerator_availability() -> None:
    assert select_inference_device(_FakeTorch(cuda=True), "auto") == "cuda"
    assert select_inference_device(_FakeTorch(mps=True), "auto") == "mps"
    assert select_inference_device(_FakeTorch(), "auto") == "cpu"
    with pytest.raises(ModelLoadError, match="CUDA"):
        select_inference_device(_FakeTorch(), "cuda")


def test_cuda_oom_is_reported_without_retry_or_silent_fallback(tmp_path: Path) -> None:
    artifact = _separate_artifact(tmp_path / "artifact")
    tokenizer = _FakeTokenizer()
    model = _FakeModel(fail_oom=True)
    analyzer = CoarseTransformerEmotionAnalyzer(
        CoarseEmotionSettings(artifact_dir=artifact, device="cpu")
    )
    with patch.object(
        analyzer,
        "_import_dependencies",
        return_value=_dependencies(tokenizer, model),
    ):
        analyzer.load()
    with pytest.raises(PredictionExecutionError, match="memory"):
        analyzer.predict(CoarseEmotionInput(hs01="합성 발화", hs02="두 번째 발화"))


def test_invalid_model_output_is_reported_as_typed_prediction_error(
    tmp_path: Path,
) -> None:
    artifact = _separate_artifact(tmp_path / "artifact")
    tokenizer = _FakeTokenizer()
    analyzer = CoarseTransformerEmotionAnalyzer(
        CoarseEmotionSettings(artifact_dir=artifact, device="cpu")
    )
    with patch.object(
        analyzer,
        "_import_dependencies",
        return_value=_dependencies(tokenizer, _FakeModel(invalid_output=True)),
    ):
        analyzer.load()
    with pytest.raises(PredictionOutputError, match="response contract"):
        analyzer.predict(CoarseEmotionInput(hs01="합성 발화", hs02="두 번째 발화"))


def test_load_rejects_blank_separator_and_training_length_mismatch(
    tmp_path: Path,
) -> None:
    artifact = _separate_artifact(tmp_path / "artifact")
    tokenizer = _FakeTokenizer()
    tokenizer.sep_token = " "
    analyzer = CoarseTransformerEmotionAnalyzer(
        CoarseEmotionSettings(artifact_dir=artifact, device="cpu")
    )
    with patch.object(
        analyzer,
        "_import_dependencies",
        return_value=_dependencies(tokenizer, _FakeModel()),
    ):
        with pytest.raises(ModelLoadError, match="separator"):
            analyzer.load()

    with pytest.raises(ValueError, match="training value 128"):
        CoarseEmotionSettings(artifact_dir=artifact, max_length=256)

    (artifact / "run_config.json").write_text(
        json.dumps(
            {"label_level": "coarse", "num_labels": 6, "max_length": 256}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ModelLoadError, match="max_length"):
        validate_coarse_artifact_metadata(resolve_coarse_artifacts(artifact_dir=artifact))


def test_settings_read_configurable_thresholds_and_paths() -> None:
    settings = CoarseEmotionSettings.from_env(
        {
            "EMOTION_MODEL_DIR": "models/coarse",
            "EMOTION_TOKENIZER_DIR": "tokenizers/coarse",
            "EMOTION_DEVICE": "CPU",
            "EMOTION_MAX_LENGTH": "128",
            "EMOTION_CONFIDENCE_THRESHOLD": "0.40",
            "EMOTION_MARGIN_THRESHOLD": "0.08",
            "EMOTION_TOP_K": "3",
        }
    )
    assert settings.model_dir == Path("models/coarse")
    assert settings.tokenizer_dir == Path("tokenizers/coarse")
    assert settings.device == "cpu"
    assert settings.confidence_threshold == 0.40
    assert settings.margin_threshold == 0.08
    assert settings.top_k == 3
