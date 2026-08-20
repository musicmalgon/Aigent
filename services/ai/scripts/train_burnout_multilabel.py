"""Train the Stage 2 six-signal multilabel model with masked BCE locally."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import random
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = AI_SERVICE_ROOT.parent
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

from ai.src.remind_ai.data.burnout_multilabel import (
    BURNOUT_SIGNAL_VALUES,
    BurnoutMultilabelSample,
    calibrate_thresholds,
    load_burnout_multilabel_jsonl,
    masked_bce_with_logits,
    validate_split_isolation,
    weighted_positive_class_weights,
)


class BurnoutMultilabelTrainingError(RuntimeError):
    """Caller-safe training failure without source text."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def select_device(torch: Any, request: str) -> Any:
    normalized = request.casefold()
    if normalized == "auto":
        normalized = "cuda" if torch.cuda.is_available() else "cpu"
    if normalized == "cuda" and not torch.cuda.is_available():
        raise BurnoutMultilabelTrainingError("CUDA was requested but is unavailable")
    if normalized not in {"cuda", "cpu"}:
        raise BurnoutMultilabelTrainingError("device must be auto, cuda, or cpu")
    return torch.device(normalized)


class BatchCollator:
    def __init__(self, tokenizer: Any, torch: Any, max_length: int) -> None:
        self.tokenizer = tokenizer
        self.torch = torch
        self.max_length = max_length

    def __call__(self, samples: Sequence[BurnoutMultilabelSample]) -> dict[str, Any]:
        encoded = self.tokenizer(
            [sample.text for sample in samples],
            truncation=True,
            max_length=self.max_length,
            padding=True,
            return_tensors="pt",
        )
        encoded["labels"] = self.torch.tensor(
            [sample.labels for sample in samples], dtype=self.torch.float32
        )
        encoded["label_mask"] = self.torch.tensor(
            [sample.label_mask for sample in samples], dtype=self.torch.float32
        )
        encoded["sample_weight"] = self.torch.tensor(
            [sample.sample_weight for sample in samples], dtype=self.torch.float32
        )
        return encoded


def _to_device(batch: dict[str, Any], device: Any) -> dict[str, Any]:
    return {name: value.to(device) for name, value in batch.items()}


def evaluate(
    model: Any,
    loader: Any,
    device: Any,
    torch: Any,
    pos_weight: Any,
) -> tuple[float, list[list[float]], list[list[float]]]:
    model.eval()
    losses: list[float] = []
    probabilities: list[list[float]] = []
    targets: list[list[float]] = []
    with torch.inference_mode():
        for batch in loader:
            moved = _to_device(batch, device)
            labels = moved.pop("labels")
            mask = moved.pop("label_mask")
            sample_weight = moved.pop("sample_weight")
            logits = model(**moved).logits
            loss = masked_bce_with_logits(
                logits,
                labels,
                mask,
                sample_weight,
                pos_weight=pos_weight,
            )
            losses.append(float(loss.detach().cpu()))
            probabilities.extend(torch.sigmoid(logits).detach().cpu().tolist())
            targets.extend(labels.detach().cpu().tolist())
    return sum(losses) / len(losses), probabilities, targets


def calibrated_metrics(
    probabilities: Sequence[Sequence[float]],
    targets: Sequence[Sequence[float]],
    calibration: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, label in enumerate(BURNOUT_SIGNAL_VALUES):
        threshold = float(calibration["labels"][label]["threshold"])
        expected = [int(row[index]) for row in targets]
        predicted = [int(float(row[index]) >= threshold) for row in probabilities]
        tp = sum(y == p == 1 for y, p in zip(expected, predicted))
        fp = sum(y == 0 and p == 1 for y, p in zip(expected, predicted))
        fn = sum(y == 1 and p == 0 for y, p in zip(expected, predicted))
        tn = sum(y == p == 0 for y, p in zip(expected, predicted))
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        )
        result[label] = {
            "threshold": threshold,
            "status": calibration["labels"][label]["status"],
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": round(precision, 6) if precision is not None else None,
            "recall": round(recall, 6) if recall is not None else None,
            "f1": round(f1, 6) if f1 is not None else None,
        }
    return result


def seed_everything(seed: int, torch: Any) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--validation-jsonl", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-model", default="klue/roberta-base")
    parser.add_argument("--base-tokenizer")
    parser.add_argument("--model-version", default="klue-roberta-stage2-burnout-signals-v1")
    parser.add_argument("--threshold-version", default="stage2-independent-human-100-v1")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--warmup-ratio", type=float, default=0.1)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--allow-download", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.epochs < 1 or args.batch_size < 1 or not 0 < args.learning_rate < 1:
        raise BurnoutMultilabelTrainingError("training hyperparameters are invalid")
    if not 32 <= args.max_length <= 512:
        raise BurnoutMultilabelTrainingError("max-length must be between 32 and 512")
    train = load_burnout_multilabel_jsonl(args.train_jsonl)
    validation = load_burnout_multilabel_jsonl(
        args.validation_jsonl, validation=True
    )
    validate_split_isolation(train, validation)
    torch = importlib.import_module("torch")
    transformers = importlib.import_module("transformers")
    seed_everything(args.seed, torch)
    device = select_device(torch, args.device)
    local_only = not args.allow_download
    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            args.base_tokenizer or args.base_model, local_files_only=local_only
        )
        model = transformers.AutoModelForSequenceClassification.from_pretrained(
            args.base_model,
            num_labels=len(BURNOUT_SIGNAL_VALUES),
            id2label={index: label for index, label in enumerate(BURNOUT_SIGNAL_VALUES)},
            label2id={label: index for index, label in enumerate(BURNOUT_SIGNAL_VALUES)},
            problem_type="multi_label_classification",
            local_files_only=local_only,
        )
    except Exception as exc:
        raise BurnoutMultilabelTrainingError(
            "base model/tokenizer could not be loaded"
        ) from exc
    classifier = getattr(model, "classifier", None)
    initializer = getattr(model, "_init_weights", None)
    if classifier is None or not callable(initializer):
        raise BurnoutMultilabelTrainingError(
            "base model does not expose a resettable classification head"
        )
    classifier.apply(initializer)
    model.to(device)
    collator = BatchCollator(tokenizer, torch, args.max_length)
    generator = torch.Generator().manual_seed(args.seed)
    train_loader = torch.utils.data.DataLoader(
        train,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collator,
        generator=generator,
    )
    validation_loader = torch.utils.data.DataLoader(
        validation,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collator,
    )
    positive_weights = weighted_positive_class_weights(train)
    pos_weight = torch.tensor(
        positive_weights, dtype=torch.float32, device=device
    )
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.learning_rate,
        weight_decay=args.weight_decay,
    )
    total_steps = len(train_loader) * args.epochs
    scheduler = transformers.get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=math.floor(total_steps * args.warmup_ratio),
        num_training_steps=total_steps,
    )
    history: list[dict[str, Any]] = []
    started = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0
        for step, batch in enumerate(train_loader, 1):
            moved = _to_device(batch, device)
            labels = moved.pop("labels")
            mask = moved.pop("label_mask")
            sample_weight = moved.pop("sample_weight")
            optimizer.zero_grad(set_to_none=True)
            logits = model(**moved).logits
            loss = masked_bce_with_logits(
                logits,
                labels,
                mask,
                sample_weight,
                pos_weight=pos_weight,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            running_loss += float(loss.detach().cpu())
            if step % 50 == 0 or step == len(train_loader):
                print(
                    f"epoch={epoch}/{args.epochs} step={step}/{len(train_loader)} "
                    f"loss={running_loss / step:.6f}",
                    flush=True,
                )
        validation_loss, _, _ = evaluate(
            model, validation_loader, device, torch, pos_weight
        )
        history.append({
            "epoch": epoch,
            "train_loss": round(running_loss / len(train_loader), 6),
            "validation_loss": round(validation_loss, 6),
        })
        print(
            f"epoch={epoch} validation_loss={validation_loss:.6f}", flush=True
        )

    validation_loss, probabilities, targets = evaluate(
        model, validation_loader, device, torch, pos_weight
    )
    calibration = calibrate_thresholds(
        probabilities,
        targets,
        minimum_precision=0.80,
        minimum_positive_support=5,
    )
    calibration["threshold_version"] = args.threshold_version
    calibration["validation_rows"] = len(validation)
    calibration["metrics"] = calibrated_metrics(
        probabilities, targets, calibration
    )
    model.config.stage2_schema_version = 1
    model.config.stage2_model_version = args.model_version
    model.config.stage2_threshold_version = args.threshold_version
    model.config.stage2_label_order = list(BURNOUT_SIGNAL_VALUES)
    model.config.stage2_deployment_status = calibration["status"]
    model_dir = args.output_dir / "model"
    tokenizer_dir = args.output_dir / "tokenizer"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(model_dir)
    tokenizer.save_pretrained(tokenizer_dir)
    atomic_json(args.output_dir / "thresholds.json", calibration)
    atomic_json(
        args.output_dir / "label_mapping.json",
        {
            "schema_version": 1,
            "labels": list(BURNOUT_SIGNAL_VALUES),
            "label2id": {
                label: index for index, label in enumerate(BURNOUT_SIGNAL_VALUES)
            },
            "id2label": {
                str(index): label for index, label in enumerate(BURNOUT_SIGNAL_VALUES)
            },
        },
    )
    run_config = {
        "artifact_role": "stage2_burnout_multilabel_model",
        "task_type": "multi_label_classification",
        "loss": "masked_bce_with_logits",
        "deployment_status": calibration["status"],
        "model_version": args.model_version,
        "threshold_version": args.threshold_version,
        "base_model": args.base_model,
        "base_tokenizer": args.base_tokenizer or args.base_model,
        "classification_head_initialized_for_stage2": True,
        "labels": list(BURNOUT_SIGNAL_VALUES),
        "train_rows": len(train),
        "validation_rows": len(validation),
        "positive_class_weights": positive_weights,
        "max_length": args.max_length,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "device": str(device),
        "history": history,
        "final_validation_loss": round(validation_loss, 6),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "input_sha256": {
            "train": file_sha256(args.train_jsonl),
            "validation": file_sha256(args.validation_jsonl),
        },
    }
    atomic_json(args.output_dir / "run_config.json", run_config)
    return {
        "status": "COMPLETE",
        "deployment_status": calibration["status"],
        "model_dir": str(model_dir),
        "tokenizer_dir": str(tokenizer_dir),
        "thresholds": str(args.output_dir / "thresholds.json"),
        "validation_rows": len(validation),
    }


def main() -> int:
    try:
        result = run(build_parser().parse_args())
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (BurnoutMultilabelTrainingError, OSError, ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
