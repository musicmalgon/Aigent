"""Evaluate product-facing emotion abstention without retraining the model."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn

AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = AI_SERVICE_ROOT.parent
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

from ai.src.emotion.coarse_settings import (  # noqa: E402
    MVP_V1_CONFIDENCE_THRESHOLD,
    MVP_V1_MARGIN_THRESHOLD,
    MVP_V1_THRESHOLD_VERSION,
    CoarseEmotionSettings,
)
from ai.src.emotion.base import EmotionAnalyzerError  # noqa: E402
from ai.src.emotion.coarse_transformer import (  # noqa: E402
    CoarseTransformerEmotionAnalyzer,
)
from ai.src.remind_ai.data.emotion_dataset import (  # noqa: E402
    TURN_SEPARATOR,
    EmotionSample,
    load_json_samples,
)
from ai.src.remind_ai.data.emotion_label_mapping import (  # noqa: E402
    load_emotion_label_mapping,
)
from ai.src.remind_ai.data.emotion_taxonomy_v2 import (  # noqa: E402
    EXPECTED_V2_LABELS,
    REMIND_COARSE_V2,
    load_emotion_label_policy_v2,
    prepare_remind_coarse_v2,
)
from ai.src.remind_ai.data.private_split_assignment import (  # noqa: E402
    load_private_split_assignment,
)
from ai.src.remind_ai.evaluation.abstention import (  # noqa: E402
    DEFAULT_CONFIDENCE_BINS,
    DEFAULT_CONFIDENCE_THRESHOLDS,
    DEFAULT_MARGIN_BINS,
    DEFAULT_MARGIN_THRESHOLDS,
    NEUTRAL_LABEL,
    AbstentionEvaluationError,
    ScoredEmotionPrediction,
    calibration_bins,
    evaluate_threshold,
    threshold_grid,
)
from ai.src.schemas import CoarseEmotionInput  # noqa: E402


class EmotionAbstentionCliError(RuntimeError):
    """A value-safe CLI failure that does not expose records or identifiers."""


def _write_json(path: Path, payload: object) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".emotion-abstention-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
    except Exception as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise EmotionAbstentionCliError(
            "an evaluation JSON output could not be written"
        ) from exc


def _write_jsonl(
    path: Path,
    predictions: Sequence[ScoredEmotionPrediction],
) -> None:
    lines = [
        json.dumps(
            {
                "sample_index": index,
                "true_label": prediction.true_label,
                "predicted_label": prediction.predicted_label,
                "confidence": prediction.confidence,
                "margin": prediction.margin,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for index, prediction in enumerate(predictions)
    ]
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".emotion-scores-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write("\n".join(lines))
            handle.write("\n")
        temporary.replace(path)
    except Exception as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise EmotionAbstentionCliError(
            "scored predictions could not be written"
        ) from exc


def _write_grid_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    fields = [
        "confidence_threshold",
        "margin_threshold",
        "acceptance_rate",
        "accepted_precision",
        "accepted_macro_f1",
        "helplessness_precision",
        "helplessness_recall",
        "helplessness_f1",
        "neutral_false_positive_rate",
    ]
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=".emotion-grid-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    except Exception as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise EmotionAbstentionCliError(
            "the threshold grid CSV could not be written"
        ) from exc


def _load_scored_predictions(path: Path) -> list[ScoredEmotionPrediction]:
    predictions: list[ScoredEmotionPrediction] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, Mapping):
                    raise EmotionAbstentionCliError(
                        "a scored prediction record is invalid"
                    )
                true_label = payload.get("true_label")
                predicted_label = payload.get("predicted_label")
                confidence = payload.get("confidence")
                margin = payload.get("margin")
                if (
                    not isinstance(true_label, str)
                    or not isinstance(predicted_label, str)
                    or not isinstance(confidence, (int, float))
                    or isinstance(confidence, bool)
                    or not isinstance(margin, (int, float))
                    or isinstance(margin, bool)
                ):
                    raise EmotionAbstentionCliError(
                        "a scored prediction record is invalid"
                    )
                predictions.append(
                    ScoredEmotionPrediction(
                        true_label=true_label,
                        predicted_label=predicted_label,
                        confidence=float(confidence),
                        margin=float(margin),
                    )
                )
    except EmotionAbstentionCliError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EmotionAbstentionCliError(
            "the scored predictions file is invalid"
        ) from exc
    if not predictions:
        raise EmotionAbstentionCliError("the scored predictions file is empty")
    return predictions


def _required_inference_arguments(arguments: argparse.Namespace) -> None:
    required = (
        "train_json",
        "validation_json",
        "split_assignment",
        "dataset_identifier",
    )
    missing = [name for name in required if getattr(arguments, name) is None]
    if missing:
        raise EmotionAbstentionCliError(
            "artifact inference requires source data, split assignment, and dataset id"
        )


def _load_test_samples(arguments: argparse.Namespace) -> list[EmotionSample]:
    _required_inference_arguments(arguments)
    source_samples = [
        *load_json_samples(Path(arguments.train_json), "official_train"),
        *load_json_samples(
            Path(arguments.validation_json), "official_validation"
        ),
    ]
    mapping = load_emotion_label_mapping(Path(arguments.label_mapping_path))
    policy = load_emotion_label_policy_v2(Path(arguments.label_policy_path))
    prepared = prepare_remind_coarse_v2(
        source_samples,
        mapping,
        policy,
        dataset_release_id=arguments.dataset_identifier,
    )
    model_samples = list(prepared.samples)
    split = load_private_split_assignment(
        Path(arguments.split_assignment).resolve(),
        model_samples,
        expected_label_set_version=REMIND_COARSE_V2,
    )
    return [model_samples[index] for index in split.test_indices]


def _request_for_sample(sample: EmotionSample) -> CoarseEmotionInput:
    turns = sample.text.split(TURN_SEPARATOR)
    if len(turns) not in {2, 3}:
        raise EmotionAbstentionCliError(
            "a prepared test sample has an unsupported turn count"
        )
    return CoarseEmotionInput(
        hs01=turns[0],
        hs02=turns[1],
        hs03=turns[2] if len(turns) == 3 else None,
    )


def _load_calibration_inputs(
    path: Path,
) -> list[tuple[str, CoarseEmotionInput]]:
    inputs: list[tuple[str, CoarseEmotionInput]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, Mapping):
                    raise EmotionAbstentionCliError(
                        "a calibration record is invalid"
                    )
                label = payload.get("label")
                turns = payload.get("turns")
                if (
                    not isinstance(label, str)
                    or label not in {*EXPECTED_V2_LABELS, NEUTRAL_LABEL}
                    or not isinstance(turns, list)
                    or len(turns) not in {2, 3}
                    or any(not isinstance(turn, str) or not turn.strip() for turn in turns)
                ):
                    raise EmotionAbstentionCliError(
                        "a calibration record is invalid"
                    )
                inputs.append(
                    (
                        label,
                        CoarseEmotionInput(
                            hs01=turns[0],
                            hs02=turns[1],
                            hs03=turns[2] if len(turns) == 3 else None,
                        ),
                    )
                )
    except EmotionAbstentionCliError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise EmotionAbstentionCliError(
            "the calibration JSONL file is invalid"
        ) from exc
    if not inputs:
        raise EmotionAbstentionCliError("the calibration JSONL file is empty")
    return inputs


def _score_artifact(arguments: argparse.Namespace) -> list[ScoredEmotionPrediction]:
    if arguments.calibration_jsonl is not None:
        inputs = _load_calibration_inputs(Path(arguments.calibration_jsonl))
    else:
        samples = _load_test_samples(arguments)
        inputs = [
            (sample.label, _request_for_sample(sample)) for sample in samples
        ]
    settings = CoarseEmotionSettings(
        artifact_dir=Path(arguments.artifact_dir),
        device=arguments.device,
        confidence_threshold=MVP_V1_CONFIDENCE_THRESHOLD,
        margin_threshold=MVP_V1_MARGIN_THRESHOLD,
        threshold_version=MVP_V1_THRESHOLD_VERSION,
        model_version=arguments.model_version,
        top_k=2,
    )
    analyzer = CoarseTransformerEmotionAnalyzer(settings)
    analyzer.load()
    predictions: list[ScoredEmotionPrediction] = []
    for start in range(0, len(inputs), arguments.batch_size):
        batch = inputs[start : start + arguments.batch_size]
        responses = analyzer.predict_batch([request for _, request in batch])
        predictions.extend(
            ScoredEmotionPrediction(
                true_label=true_label,
                predicted_label=response.predicted_emotion.value,
                confidence=float(response.confidence),
                margin=float(response.margin),
            )
            for (true_label, _), response in zip(batch, responses, strict=True)
        )
        print(f"Scored {min(start + len(batch), len(inputs))}/{len(inputs)}")
    return predictions


def _grid_row(result: Mapping[str, object]) -> dict[str, object]:
    fields = (
        "confidence_threshold",
        "margin_threshold",
        "acceptance_rate",
        "accepted_precision",
        "accepted_macro_f1",
        "helplessness_precision",
        "helplessness_recall",
        "helplessness_f1",
        "neutral_false_positive_rate",
    )
    return {field: result.get(field) for field in fields}


def run(arguments: argparse.Namespace) -> dict[str, object]:
    if (
        not isinstance(arguments.model_version, str)
        or not arguments.model_version.strip()
        or not isinstance(arguments.dataset_identifier, str)
        or not arguments.dataset_identifier.strip()
    ):
        raise EmotionAbstentionCliError(
            "model version and dataset identifier must not be empty"
        )
    output_dir = Path(arguments.output_dir)
    if arguments.scored_predictions is not None:
        predictions = _load_scored_predictions(Path(arguments.scored_predictions))
        source = "scored_predictions"
    else:
        predictions = _score_artifact(arguments)
        source = (
            "artifact_calibration_inference"
            if arguments.calibration_jsonl is not None
            else "artifact_test_inference"
        )
        _write_jsonl(output_dir / "scored_predictions.jsonl", predictions)

    current = evaluate_threshold(
        predictions,
        confidence_threshold=MVP_V1_CONFIDENCE_THRESHOLD,
        margin_threshold=MVP_V1_MARGIN_THRESHOLD,
    )
    grid_results = threshold_grid(
        predictions,
        confidence_thresholds=DEFAULT_CONFIDENCE_THRESHOLDS,
        margin_thresholds=DEFAULT_MARGIN_THRESHOLDS,
    )
    grid_rows = [_grid_row(result) for result in grid_results]
    metadata = {
        "model_version": arguments.model_version,
        "taxonomy_version": REMIND_COARSE_V2,
        "dataset_identifier": arguments.dataset_identifier,
        "source": source,
        "sample_count": len(predictions),
        "neutral_evaluation_available": current["neutral_sample_count"] != 0,
        "threshold_grid": {
            "confidence": list(DEFAULT_CONFIDENCE_THRESHOLDS),
            "margin": list(DEFAULT_MARGIN_THRESHOLDS),
        },
    }
    _write_json(
        output_dir / "current_threshold_metrics.json",
        {"metadata": metadata, "metrics": current},
    )
    _write_json(
        output_dir / "threshold_grid.json",
        {"metadata": metadata, "results": grid_rows},
    )
    _write_grid_csv(output_dir / "threshold_grid.csv", grid_rows)
    _write_json(
        output_dir / "confidence_bins.json",
        {
            "metadata": metadata,
            "bins": calibration_bins(
                predictions,
                field="confidence",
                boundaries=DEFAULT_CONFIDENCE_BINS,
            ),
        },
    )
    _write_json(
        output_dir / "margin_bins.json",
        {
            "metadata": metadata,
            "bins": calibration_bins(
                predictions,
                field="margin",
                boundaries=DEFAULT_MARGIN_BINS,
            ),
        },
    )
    return {"metadata": metadata, "current_threshold": current, "grid": grid_rows}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate confidence-and-margin emotion abstention from cached scores "
            "or one local model inference pass."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scored-predictions")
    source.add_argument("--artifact-dir")
    parser.add_argument("--calibration-jsonl")
    parser.add_argument("--train-json")
    parser.add_argument("--validation-json")
    parser.add_argument("--split-assignment")
    parser.add_argument("--dataset-identifier", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--model-version", default="klue-roberta-remind-coarse-v2"
    )
    parser.add_argument(
        "--label-mapping-path",
        default=str(AI_SERVICE_ROOT / "config" / "emotion_label_mapping.json"),
    )
    parser.add_argument(
        "--label-policy-path",
        default=str(AI_SERVICE_ROOT / "config" / "emotion_label_policy_v2.json"),
    )
    parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda", "mps"), default="auto"
    )
    parser.add_argument("--batch-size", type=int, default=32)
    return parser


def _fail(message: str) -> NoReturn:
    print(f"Emotion abstention evaluation failed: {message}", file=sys.stderr)
    raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.batch_size < 1:
            raise EmotionAbstentionCliError("batch-size must be positive")
        result = run(arguments)
    except (
        EmotionAbstentionCliError,
        AbstentionEvaluationError,
        EmotionAnalyzerError,
        ValueError,
    ) as exc:
        _fail(str(exc))
    current = result["current_threshold"]
    assert isinstance(current, Mapping)
    print("=" * 60)
    print("Emotion abstention evaluation completed")
    print("=" * 60)
    print(f"Samples             : {current['total_count']}")
    print(f"Accepted            : {current['accepted_count']}")
    print(f"Acceptance rate     : {current['acceptance_rate']:.6f}")
    print(f"Accepted precision  : {current['accepted_precision']:.6f}")
    print(f"Accepted macro F1   : {current['accepted_macro_f1']:.6f}")
    print(f"Helplessness F1     : {current['helplessness_f1']:.6f}")
    neutral_fpr = current["neutral_false_positive_rate"]
    print(
        "Neutral FPR         : "
        + ("unavailable" if neutral_fpr is None else f"{neutral_fpr:.6f}")
    )
    print(f"Output directory    : {arguments.output_dir}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
