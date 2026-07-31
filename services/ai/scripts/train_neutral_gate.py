"""Train and calibrate the KLUE-RoBERTa neutral/emotional gate."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn

AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = AI_SERVICE_ROOT.parent
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

from ai.src.remind_ai.data.neutral_gate_dataset import (  # noqa: E402
    NEUTRAL_GATE_LABELS,
    NeutralGateDatasetError,
    load_neutral_gate_dataset,
)
from ai.src.remind_ai.data.transformer_dataset import (  # noqa: E402
    TokenizedEmotionDataset,
    build_label_encoding,
)
from ai.src.remind_ai.evaluation.neutral_gate import (  # noqa: E402
    NeutralGateEvaluationError,
    ScoredGatePrediction,
    evaluate_gate_threshold,
    select_gate_threshold,
    threshold_sweep,
)
from ai.src.remind_ai.models.transformer_classifier import (  # noqa: E402
    TransformerModelConfig,
    create_data_collator,
    load_classifier,
    load_tokenizer,
    select_device,
)
from ai.src.remind_ai.training.transformer_trainer import (  # noqa: E402
    TrainingConfig,
    fit,
    make_dataloader,
    seed_everything,
)


class NeutralGateTrainingFailure(RuntimeError):
    pass


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _ratio(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("value must be between zero and one")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return parsed


def _write_json(path: Path, payload: object) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".neutral-gate-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
        temporary.replace(path)
    except Exception as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise NeutralGateTrainingFailure(
            "a neutral gate artifact file could not be written"
        ) from exc


def _score(
    *,
    torch: Any,
    model: Any,
    loader: Any,
    labels: Any,
    device: Any,
) -> list[ScoredGatePrediction]:
    model.eval()
    predictions: list[ScoredGatePrediction] = []
    with torch.inference_mode():
        for batch in loader:
            expected = batch.pop("labels")
            moved = {
                name: value.to(device) if hasattr(value, "to") else value
                for name, value in batch.items()
            }
            probabilities = (
                torch.softmax(model(**moved).logits, dim=-1).detach().cpu().tolist()
            )
            expected_ids = expected.detach().cpu().tolist()
            if len(probabilities) != len(expected_ids):
                raise NeutralGateTrainingFailure("gate score batch size is invalid")
            predictions.extend(
                ScoredGatePrediction(
                    true_label=labels.id2label[int(expected_id)],
                    emotional_probability=float(row[1]),
                )
                for expected_id, row in zip(expected_ids, probabilities, strict=True)
            )
    return predictions


def _artifact_metadata(
    *,
    arguments: argparse.Namespace,
    threshold: float,
    best_epoch: int,
) -> dict[str, object]:
    return {
        "model_version": arguments.model_version,
        "base_model": arguments.model_name,
        "labels": list(NEUTRAL_GATE_LABELS),
        "gate_threshold": threshold,
        "training_seed": arguments.random_state,
        "taxonomy_version": "v2",
        "intended_use": "neutral gate before six-class emotion classification",
        "best_epoch": best_epoch,
    }


def run(arguments: argparse.Namespace) -> None:
    output_dir = Path(arguments.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise NeutralGateTrainingFailure("output directory must be empty")
    dataset = load_neutral_gate_dataset(Path(arguments.dataset_jsonl))
    all_samples = tuple(
        sample
        for split_samples in dataset.samples_by_split.values()
        for sample in split_samples
    )
    labels = build_label_encoding(all_samples, classes=NEUTRAL_GATE_LABELS)
    selection = select_device(
        arguments.device,
        allow_cpu_fallback=arguments.allow_cpu_fallback,
        fp16_requested=arguments.fp16,
    )
    try:
        torch = importlib.import_module("torch")
    except ImportError as exc:
        raise NeutralGateTrainingFailure("PyTorch is required") from exc
    seed_everything(torch, arguments.random_state)
    tokenizer = load_tokenizer(arguments.model_name)
    model = load_classifier(
        TransformerModelConfig(
            model_name=arguments.model_name,
            max_length=arguments.max_length,
        ),
        labels,
    )
    device = torch.device(selection.selected)
    collator = create_data_collator(tokenizer)

    datasets = {
        split: TokenizedEmotionDataset(
            samples,
            tokenizer,
            labels,
            max_length=arguments.max_length,
        )
        for split, samples in dataset.samples_by_split.items()
    }
    loaders = {
        split: make_dataloader(
            torch,
            tokenized,
            collator,
            batch_size=(
                arguments.train_batch_size
                if split == "train"
                else arguments.eval_batch_size
            ),
            shuffle=split == "train",
            num_workers=arguments.num_workers,
            random_state=arguments.random_state,
        )
        for split, tokenized in datasets.items()
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    training_config = TrainingConfig(
        epochs=arguments.epochs,
        learning_rate=arguments.learning_rate,
        train_batch_size=arguments.train_batch_size,
        eval_batch_size=arguments.eval_batch_size,
        gradient_accumulation_steps=arguments.gradient_accumulation_steps,
        weight_decay=arguments.weight_decay,
        warmup_ratio=arguments.warmup_ratio,
        early_stopping_patience=arguments.early_stopping_patience,
        random_state=arguments.random_state,
        num_workers=arguments.num_workers,
        fp16=arguments.fp16,
        progress_bar=not arguments.disable_progress_bar,
        checkpoint_provenance={
            "task": "neutral_gate",
            "model_version": arguments.model_version,
            "dataset_release_id": arguments.dataset_release_id,
            "labels": list(NEUTRAL_GATE_LABELS),
            "random_state": arguments.random_state,
        },
    )
    result = fit(
        torch=torch,
        model=model,
        tokenizer=tokenizer,
        train_loader=loaders["train"],
        validation_loader=loaders["validation"],
        labels=labels,
        device=device,
        checkpoints_dir=output_dir / "checkpoints",
        config=training_config,
    )

    calibration_scores = _score(
        torch=torch,
        model=model,
        loader=loaders["calibration"],
        labels=labels,
        device=device,
    )
    sweep = threshold_sweep(calibration_scores)
    selected = select_gate_threshold(sweep)
    threshold = float(selected["threshold"])
    test_scores = _score(
        torch=torch,
        model=model,
        loader=loaders["test"],
        labels=labels,
        device=device,
    )
    test_metrics = evaluate_gate_threshold(test_scores, threshold=threshold)

    model_dir = output_dir / "model"
    tokenizer_dir = output_dir / "tokenizer"
    model.save_pretrained(model_dir, safe_serialization=True)
    tokenizer.save_pretrained(tokenizer_dir)
    _write_json(
        output_dir / "label_classes.json",
        {
            "classes": list(NEUTRAL_GATE_LABELS),
            "label2id": dict(labels.label2id),
            "id2label": {str(index): label for index, label in labels.id2label.items()},
        },
    )
    _write_json(
        output_dir / "model_metadata.json",
        _artifact_metadata(
            arguments=arguments,
            threshold=threshold,
            best_epoch=result.best_epoch,
        ),
    )
    _write_json(
        output_dir / "training_config.json",
        {
            "dataset_release_id": arguments.dataset_release_id,
            "model_name": arguments.model_name,
            "model_version": arguments.model_version,
            "max_length": arguments.max_length,
            "epochs": arguments.epochs,
            "learning_rate": arguments.learning_rate,
            "train_batch_size": arguments.train_batch_size,
            "eval_batch_size": arguments.eval_batch_size,
            "gradient_accumulation_steps": arguments.gradient_accumulation_steps,
            "weight_decay": arguments.weight_decay,
            "warmup_ratio": arguments.warmup_ratio,
            "early_stopping_patience": arguments.early_stopping_patience,
            "random_state": arguments.random_state,
            "device": selection.selected,
            "fp16": arguments.fp16,
            "best_validation_macro_f1": result.best_validation_macro_f1,
            "best_epoch": result.best_epoch,
            "stopped_early": result.stopped_early,
            "optimizer_step_count": result.optimizer_step_count,
            "total_elapsed_seconds": result.total_elapsed_seconds,
            "training_history": list(result.history),
        },
    )
    _write_json(
        output_dir / "calibration_metrics.json",
        {
            "selected": selected,
            "threshold_sweep": sweep,
            "selection_dataset": "calibration",
            "final_test_was_not_used_for_threshold_selection": True,
        },
    )
    _write_json(
        output_dir / "test_metrics.json",
        {
            **test_metrics,
            "evaluated_once_after_threshold_selection": True,
        },
    )
    _write_json(output_dir / "split_summary.json", dataset.summary)
    shutil.rmtree(output_dir / "checkpoints", ignore_errors=True)
    print("=" * 60)
    print("Neutral gate training completed")
    print("=" * 60)
    print(f"Best epoch          : {result.best_epoch}")
    print(f"Selected threshold  : {threshold:.2f}")
    print(
        "Test neutral FPR    : "
        f"{float(test_metrics['neutral_false_positive_rate']):.6f}"
    )
    print(f"Emotional retention: {float(test_metrics['emotional_retention']):.6f}")
    print(f"Output directory    : {output_dir}")
    print("=" * 60)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train a calibrated KLUE-RoBERTa neutral/emotional gate."
    )
    parser.add_argument("--dataset-jsonl", required=True)
    parser.add_argument("--dataset-release-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model-version", default="neutral-gate-klue-roberta-v1")
    parser.add_argument("--model-name", default="klue/roberta-base")
    parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda", "mps"), default="auto"
    )
    parser.add_argument("--allow-cpu-fallback", action="store_true")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--max-length", type=_positive_int, default=128)
    parser.add_argument("--epochs", type=_positive_int, default=3)
    parser.add_argument("--learning-rate", type=_positive_float, default=2e-5)
    parser.add_argument("--train-batch-size", type=_positive_int, default=8)
    parser.add_argument("--eval-batch-size", type=_positive_int, default=16)
    parser.add_argument(
        "--gradient-accumulation-steps",
        type=_positive_int,
        default=2,
    )
    parser.add_argument("--weight-decay", type=_ratio, default=0.01)
    parser.add_argument("--warmup-ratio", type=_ratio, default=0.1)
    parser.add_argument("--early-stopping-patience", type=_positive_int, default=1)
    parser.add_argument("--random-state", type=int, default=777)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--disable-progress-bar", action="store_true")
    return parser


def _fail(message: str) -> NoReturn:
    print(f"Neutral gate training failed: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    try:
        run(_parser().parse_args())
    except (
        NeutralGateDatasetError,
        NeutralGateEvaluationError,
        NeutralGateTrainingFailure,
        RuntimeError,
        ValueError,
    ) as exc:
        _fail(str(exc))
