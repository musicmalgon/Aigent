"""Small, privacy-safe PyTorch trainer for the transformer baseline."""

from __future__ import annotations

import json
import math
import random
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..data.transformer_dataset import LabelEncoding
from ..models.transformer_classifier import classification_metrics
from .progress import (
    ProgressConfig,
    ProgressReporter,
    epoch_summary,
    format_duration,
)


class TransformerTrainingError(RuntimeError):
    """Training failure whose message excludes source values and paths."""


@dataclass(frozen=True)
class TrainingConfig:
    epochs: int = 3
    learning_rate: float = 2e-5
    train_batch_size: int = 8
    eval_batch_size: int = 16
    gradient_accumulation_steps: int = 2
    weight_decay: float = 0.01
    warmup_ratio: float = 0.1
    max_grad_norm: float = 1.0
    early_stopping_patience: int = 2
    random_state: int = 42
    num_workers: int = 0
    fp16: bool = False
    progress_bar: bool = True
    progress_update_interval: int = 1
    show_gpu_memory: bool = False
    log_every_n_steps: int = 0
    class_weights: tuple[float, ...] | None = None
    checkpoint_provenance: Mapping[str, object] | None = None


@dataclass(frozen=True)
class TrainingResult:
    best_epoch: int
    best_validation_macro_f1: float
    history: tuple[Mapping[str, object], ...]
    stopped_early: bool
    optimizer_step_count: int
    total_elapsed_seconds: float


def _normalize_checkpoint_provenance(
    provenance: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if provenance is None:
        return None
    try:
        encoded = json.dumps(
            dict(provenance),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise TransformerTrainingError(
            "checkpoint provenance must be finite JSON data"
        ) from exc
    if not isinstance(decoded, dict):
        raise TransformerTrainingError("checkpoint provenance must be an object")
    return decoded


def seed_everything(torch: Any, random_state: int) -> None:
    """Seed Python and PyTorch consistently across supported devices."""

    random.seed(random_state)
    torch.manual_seed(random_state)
    if bool(torch.cuda.is_available()):
        torch.cuda.manual_seed_all(random_state)
    deterministic = getattr(torch, "use_deterministic_algorithms", None)
    if callable(deterministic):
        try:
            deterministic(True, warn_only=True)
        except TypeError:  # pragma: no cover - older compatible torch
            deterministic(True)


def make_dataloader(
    torch: Any,
    dataset: Any,
    collator: Any,
    *,
    batch_size: int,
    shuffle: bool,
    num_workers: int,
    random_state: int = 42,
) -> Any:
    generator = torch.Generator()
    generator.manual_seed(random_state)
    return torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        collate_fn=collator,
        generator=generator,
    )


def _synchronize_device(torch: Any, device: Any) -> None:
    device_type = getattr(device, "type", str(device))
    if device_type == "cuda":
        torch.cuda.synchronize()
    elif device_type == "mps":
        mps = getattr(torch, "mps", None)
        synchronize = getattr(mps, "synchronize", None)
        if callable(synchronize):
            synchronize()


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
    return ordered[index]


def benchmark_inference(
    *,
    torch: Any,
    model: Any,
    batch_factory: Callable[[], Mapping[str, Any]],
    device: Any,
    effective_batch_size: int,
    warmup_runs: int,
    measured_runs: int,
    fp16: bool = False,
) -> dict[str, object]:
    """Measure tokenization/collation, transfer, and forward latency safely."""

    if effective_batch_size < 1 or warmup_runs < 0 or measured_runs < 1:
        raise TransformerTrainingError(
            "the inference benchmark configuration is invalid"
        )

    def predict_once() -> None:
        batch = batch_factory()
        if not isinstance(batch, Mapping):
            raise TransformerTrainingError("the inference benchmark batch is invalid")
        moved = _to_device(batch, device)
        moved.pop("labels", None)
        precision_context = (
            torch.autocast(device_type="cuda", dtype=torch.float16)
            if fp16
            else nullcontext()
        )
        with precision_context:
            model(**moved)

    model.eval()
    with torch.no_grad():
        for _ in range(warmup_runs):
            predict_once()
        _synchronize_device(torch, device)
        timings_ms: list[float] = []
        for _ in range(measured_runs):
            started = time.perf_counter()
            predict_once()
            _synchronize_device(torch, device)
            timings_ms.append((time.perf_counter() - started) * 1_000)
    total_seconds = sum(timings_ms) / 1_000
    return {
        "effective_batch_size": effective_batch_size,
        "warmup_runs": warmup_runs,
        "measured_runs": measured_runs,
        "p50_latency_ms": round(_percentile(timings_ms, 0.50), 6),
        "p95_latency_ms": round(_percentile(timings_ms, 0.95), 6),
        "samples_per_second": round(
            effective_batch_size * measured_runs / max(total_seconds, 1e-12), 3
        ),
        "fp16_enabled": fp16,
    }


def _to_device(batch: Mapping[str, Any], device: Any) -> dict[str, Any]:
    return {
        name: value.to(device) if hasattr(value, "to") else value
        for name, value in batch.items()
    }


def evaluate_with_predictions(
    torch: Any,
    model: Any,
    loader: Any,
    device: Any,
    labels: LabelEncoding,
    *,
    reporter: ProgressReporter | None = None,
    desc: str = "Evaluation",
) -> tuple[dict[str, object], list[int], list[int]]:
    """Evaluate one loader once, returning aggregate metrics and in-memory label IDs."""

    reporter = reporter or ProgressReporter(ProgressConfig(enabled=False))
    expected: list[int] = []
    predicted: list[int] = []
    running_loss = 0.0
    processed_samples = 0
    model.eval()
    bar = reporter.batches(loader, total=len(loader), desc=desc)
    with torch.no_grad():
        for batch_index, batch in enumerate(bar, start=1):
            moved = _to_device(batch, device)
            label_values = moved.get("labels")
            if label_values is None:
                raise TransformerTrainingError("an evaluation batch is missing labels")
            outputs = model(**moved)
            loss = getattr(outputs, "loss", None)
            if loss is None:
                raise TransformerTrainingError("evaluation loss is unavailable")
            predictions = outputs.logits.argmax(dim=-1)
            batch_size = int(label_values.shape[0])
            loss_value = float(loss.detach().cpu().item())
            running_loss += loss_value * batch_size
            processed_samples += batch_size
            expected.extend(
                int(value) for value in label_values.detach().cpu().tolist()
            )
            predicted.extend(
                int(value) for value in predictions.detach().cpu().tolist()
            )
            reporter.update_postfix(
                bar,
                batch_index,
                {
                    "avg_loss": f"{running_loss / max(processed_samples, 1):.4f}",
                    "samples": processed_samples,
                },
            )
    metrics = classification_metrics(expected, predicted, labels)
    metrics["loss"] = round(running_loss / max(processed_samples, 1), 6)
    return metrics, expected, predicted


def predict_ids(
    torch: Any, model: Any, loader: Any, device: Any
) -> tuple[list[int], list[int]]:
    """Run batched no-grad prediction and return class IDs only in memory."""

    expected: list[int] = []
    predicted: list[int] = []
    model.eval()
    with torch.no_grad():
        for batch in loader:
            moved = _to_device(batch, device)
            label_values = moved.pop("labels")
            outputs = model(**moved)
            predictions = outputs.logits.argmax(dim=-1)
            expected.extend(
                int(value) for value in label_values.detach().cpu().tolist()
            )
            predicted.extend(
                int(value) for value in predictions.detach().cpu().tolist()
            )
    return expected, predicted


def evaluate(
    torch: Any,
    model: Any,
    loader: Any,
    device: Any,
    labels: LabelEncoding,
    *,
    reporter: ProgressReporter | None = None,
    desc: str = "Evaluation",
) -> dict[str, object]:
    metrics, _, _ = evaluate_with_predictions(
        torch,
        model,
        loader,
        device,
        labels,
        reporter=reporter,
        desc=desc,
    )
    return metrics


def _save_checkpoint(
    model: Any,
    tokenizer: Any,
    directory: Path,
    *,
    torch: Any,
    optimizer: Any | None = None,
    scheduler: Any | None = None,
    trainer_state: Mapping[str, object] | None = None,
) -> None:
    """Replace a checkpoint directory only after both artifacts save successfully."""

    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".transformer-checkpoint-", dir=directory.parent)
    )
    backup = directory.parent / f".{directory.name}.previous"
    existing_moved = False
    try:
        if backup.exists():
            if directory.exists():
                shutil.rmtree(backup)
            else:
                backup.replace(directory)
        try:
            model.save_pretrained(temporary, safe_serialization=False)
        except TypeError:  # synthetic stubs and older compatible transformers
            model.save_pretrained(temporary)
        tokenizer.save_pretrained(temporary)
        if (
            optimizer is not None
            and scheduler is not None
            and trainer_state is not None
        ):
            torch.save(
                {
                    "optimizer": optimizer.state_dict(),
                    "scheduler": scheduler.state_dict(),
                },
                temporary / "training_state.pt",
            )
            (temporary / "trainer_state.json").write_text(
                json.dumps(dict(trainer_state), ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        if directory.exists():
            directory.replace(backup)
            existing_moved = True
        try:
            temporary.replace(directory)
        except BaseException:
            if existing_moved and backup.exists() and not directory.exists():
                backup.replace(directory)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        if existing_moved and backup.exists() and not directory.exists():
            backup.replace(directory)
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise TransformerTrainingError(
            "a training checkpoint could not be saved"
        ) from exc


def fit(
    *,
    torch: Any,
    model: Any,
    tokenizer: Any,
    train_loader: Any,
    validation_loader: Any,
    labels: LabelEncoding,
    device: Any,
    checkpoints_dir: Path,
    config: TrainingConfig,
    resume_from_checkpoint: Path | None = None,
) -> TrainingResult:
    """Train, select by validation macro-F1, and reload the best checkpoint."""

    if (
        config.epochs < 1
        or config.gradient_accumulation_steps < 1
        or config.progress_update_interval < 1
        or config.log_every_n_steps < 0
    ):
        raise TransformerTrainingError("training counts must be positive")
    if (
        not math.isfinite(config.learning_rate)
        or config.learning_rate <= 0
        or not math.isfinite(config.weight_decay)
        or config.weight_decay < 0
        or not math.isfinite(config.warmup_ratio)
        or not 0 <= config.warmup_ratio <= 1
        or not math.isfinite(config.max_grad_norm)
        or config.max_grad_norm <= 0
    ):
        raise TransformerTrainingError(
            "training hyperparameters must be finite and in range"
        )
    if config.class_weights is not None and (
        len(config.class_weights) != len(labels.classes)
        or any(not math.isfinite(value) or value <= 0 for value in config.class_weights)
    ):
        raise TransformerTrainingError(
            "class weights must match the positive finite label vocabulary"
        )
    checkpoint_provenance = _normalize_checkpoint_provenance(
        config.checkpoint_provenance
    )
    if resume_from_checkpoint is not None and checkpoint_provenance is None:
        raise TransformerTrainingError("resume requires explicit checkpoint provenance")
    reporter = ProgressReporter(
        ProgressConfig(
            enabled=config.progress_bar,
            update_interval=config.progress_update_interval,
            show_gpu_memory=config.show_gpu_memory,
        )
    )
    fit_started = time.perf_counter()
    seed_everything(torch, config.random_state)
    model.to(device)
    class_weight_tensor = (
        torch.tensor(config.class_weights, dtype=torch.float32, device=device)
        if config.class_weights is not None
        else None
    )
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    updates_per_epoch = max(
        1, math.ceil(len(train_loader) / config.gradient_accumulation_steps)
    )
    total_updates = updates_per_epoch * config.epochs
    warmup_updates = int(total_updates * config.warmup_ratio)

    def lr_factor(step: int) -> float:
        if warmup_updates and step < warmup_updates:
            return max((step + 1) / warmup_updates, 1e-8)
        remaining = max(total_updates - step, 0)
        denominator = max(total_updates - warmup_updates, 1)
        return remaining / denominator

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_factor)
    scaler: Any | None = None
    if config.fp16:
        try:
            scaler = torch.amp.GradScaler("cuda", enabled=True)
        except (AttributeError, TypeError):  # pragma: no cover - older compatible torch
            scaler = torch.cuda.amp.GradScaler(enabled=True)
    best_score = -1.0
    best_epoch = 0
    epochs_without_improvement = 0
    optimizer_steps = 0
    history: list[Mapping[str, object]] = []
    best_directory = checkpoints_dir / "best"
    best_load_directory = best_directory
    start_epoch = 1
    if resume_from_checkpoint is not None:
        try:
            state_payload = json.loads(
                (resume_from_checkpoint / "trainer_state.json").read_text(
                    encoding="utf-8"
                )
            )
            try:
                optimizer_payload = torch.load(
                    resume_from_checkpoint / "training_state.pt",
                    map_location=device,
                    weights_only=True,
                )
            except TypeError:  # pragma: no cover - older compatible torch
                optimizer_payload = torch.load(
                    resume_from_checkpoint / "training_state.pt",
                    map_location=device,
                )
            if not isinstance(state_payload, Mapping) or not isinstance(
                optimizer_payload, Mapping
            ):
                raise TypeError
            if state_payload.get("checkpoint_provenance") != checkpoint_provenance:
                raise TypeError
            optimizer.load_state_dict(optimizer_payload["optimizer"])
            scheduler.load_state_dict(optimizer_payload["scheduler"])
            completed_epoch_value = state_payload["completed_epoch"]
            best_epoch_value = state_payload["best_epoch"]
            best_score_value = state_payload["best_validation_macro_f1"]
            optimizer_steps_value = state_payload["optimizer_step_count"]
            epochs_without_value = state_payload["epochs_without_improvement"]
            if not all(
                isinstance(value, (int, float))
                for value in (
                    completed_epoch_value,
                    best_epoch_value,
                    best_score_value,
                    optimizer_steps_value,
                    epochs_without_value,
                )
            ):
                raise ValueError
            completed_epoch = int(completed_epoch_value)
            start_epoch = completed_epoch + 1
            best_epoch = int(best_epoch_value)
            best_score = float(best_score_value)
            optimizer_steps = int(optimizer_steps_value)
            epochs_without_improvement = int(epochs_without_value)
            loaded_history = state_payload.get("history", [])
            if not isinstance(loaded_history, list):
                raise TypeError
            expected_class_weights = (
                list(config.class_weights) if config.class_weights is not None else None
            )
            if state_payload.get("class_weights") != expected_class_weights:
                raise TypeError
            history = [item for item in loaded_history if isinstance(item, Mapping)]
            if best_epoch > 0:
                previous_best = (
                    resume_from_checkpoint
                    if resume_from_checkpoint.name == "best"
                    else resume_from_checkpoint.parent / "best"
                )
                previous_best_state = json.loads(
                    (previous_best / "trainer_state.json").read_text(encoding="utf-8")
                )
                if (
                    not isinstance(previous_best_state, Mapping)
                    or previous_best_state.get("completed_epoch") != best_epoch
                    or previous_best_state.get("best_epoch") != best_epoch
                    or previous_best_state.get("best_validation_macro_f1") != best_score
                    or previous_best_state.get("class_weights")
                    != expected_class_weights
                    or previous_best_state.get("checkpoint_provenance")
                    != checkpoint_provenance
                    or not (previous_best / "pytorch_model.bin").is_file()
                ):
                    raise TypeError
                best_load_directory = previous_best
        except Exception as exc:
            raise TransformerTrainingError(
                "the resume checkpoint does not contain valid trainer state"
            ) from exc
        if start_epoch > config.epochs:
            raise TransformerTrainingError(
                "the resume checkpoint already reached the requested epoch count"
            )
    current_epoch = start_epoch - 1
    try:
        for epoch in range(start_epoch, config.epochs + 1):
            current_epoch = epoch
            epoch_started = time.perf_counter()
            train_started = time.perf_counter()
            model.train()
            optimizer.zero_grad(set_to_none=True)
            running_loss = 0.0
            batch_count = 0
            train_bar = reporter.batches(
                train_loader,
                total=len(train_loader),
                desc=f"Epoch {epoch}/{config.epochs} [Train]",
            )
            for batch_index, batch in enumerate(train_bar, start=1):
                moved = _to_device(batch, device)
                precision_context = (
                    torch.autocast(device_type="cuda", dtype=torch.float16)
                    if config.fp16
                    else nullcontext()
                )
                with precision_context:
                    if class_weight_tensor is None:
                        outputs = model(**moved)
                        raw_loss = getattr(outputs, "loss", None)
                        if raw_loss is None:
                            raise TransformerTrainingError(
                                "training loss is unavailable"
                            )
                    else:
                        label_values = moved.pop("labels", None)
                        if label_values is None:
                            raise TransformerTrainingError(
                                "a training batch is missing labels"
                            )
                        outputs = model(**moved)
                        logits = getattr(outputs, "logits", None)
                        if logits is None:
                            raise TransformerTrainingError(
                                "training logits are unavailable"
                            )
                        raw_loss = torch.nn.functional.cross_entropy(
                            logits,
                            label_values,
                            weight=class_weight_tensor,
                        )
                    loss = raw_loss / config.gradient_accumulation_steps
                if scaler is not None:
                    scaler.scale(loss).backward()
                else:
                    loss.backward()
                current_loss = float(raw_loss.detach().cpu().item())
                running_loss += current_loss
                batch_count += 1
                should_step = (
                    batch_index % config.gradient_accumulation_steps == 0
                    or batch_index == len(train_loader)
                )
                if should_step:
                    if scaler is not None:
                        scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(
                        model.parameters(), config.max_grad_norm
                    )
                    if scaler is not None:
                        scaler.step(optimizer)
                        scaler.update()
                    else:
                        optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad(set_to_none=True)
                    optimizer_steps += 1
                    if (
                        config.log_every_n_steps
                        and optimizer_steps % config.log_every_n_steps == 0
                    ):
                        reporter.write(
                            f"optimizer step {optimizer_steps}: "
                            f"avg_loss={running_loss / max(batch_count, 1):.4f}"
                        )
                postfix: dict[str, object] = {
                    "loss": f"{current_loss:.4f}",
                    "avg_loss": f"{running_loss / max(batch_count, 1):.4f}",
                    "lr": f"{float(optimizer.param_groups[0]['lr']):.2e}",
                    "step": optimizer_steps,
                    "accum": (
                        f"{((batch_index - 1) % config.gradient_accumulation_steps) + 1}/"
                        f"{config.gradient_accumulation_steps}"
                    ),
                }
                memory = reporter.gpu_memory(torch, device)
                if memory is not None:
                    postfix["vram"] = memory
                reporter.update_postfix(train_bar, batch_index, postfix)
            train_seconds = time.perf_counter() - train_started
            validation_started = time.perf_counter()
            validation = evaluate(
                torch,
                model,
                validation_loader,
                device,
                labels,
                reporter=reporter,
                desc=f"Epoch {epoch}/{config.epochs} [Validation]",
            )
            validation_seconds = time.perf_counter() - validation_started
            epoch_seconds = time.perf_counter() - epoch_started
            score_value = validation.get("macro_f1")
            if not isinstance(score_value, (int, float)):
                raise TransformerTrainingError("validation macro-F1 is invalid")
            score = float(score_value)
            train_loss = running_loss / max(batch_count, 1)
            improved = score > best_score
            if improved:
                best_score = score
                best_epoch = epoch
                epochs_without_improvement = 0
                best_load_directory = best_directory
            else:
                epochs_without_improvement += 1
            learning_rate = float(optimizer.param_groups[0]["lr"])
            total_elapsed_seconds = time.perf_counter() - fit_started
            completed_in_run = epoch - start_epoch + 1
            remaining_epochs = config.epochs - epoch
            estimated_remaining_seconds = (
                total_elapsed_seconds / max(completed_in_run, 1) * remaining_epochs
            )
            history.append(
                {
                    "epoch": epoch,
                    "train_loss": round(train_loss, 6),
                    "validation_loss": validation.get("loss"),
                    "validation_metrics": validation,
                    "learning_rate": learning_rate,
                    "optimizer_step_count": optimizer_steps,
                    "best_checkpoint_updated": improved,
                    "best_epoch": best_epoch,
                    "best_validation_macro_f1": best_score,
                    "early_stopping_count": epochs_without_improvement,
                    "train_seconds": round(train_seconds, 6),
                    "validation_seconds": round(validation_seconds, 6),
                    "epoch_seconds": round(epoch_seconds, 6),
                    "total_elapsed_seconds": round(total_elapsed_seconds, 6),
                    "estimated_remaining_seconds": round(
                        estimated_remaining_seconds, 6
                    ),
                    "train_duration": format_duration(train_seconds),
                    "validation_duration": format_duration(validation_seconds),
                    "epoch_duration": format_duration(epoch_seconds),
                    "total_elapsed_duration": format_duration(total_elapsed_seconds),
                    "estimated_remaining_duration": format_duration(
                        estimated_remaining_seconds
                    ),
                }
            )
            trainer_state = {
                "completed_epoch": epoch,
                "best_epoch": best_epoch,
                "best_validation_macro_f1": best_score,
                "optimizer_step_count": optimizer_steps,
                "epochs_without_improvement": epochs_without_improvement,
                "history": history,
                "class_weights": (
                    list(config.class_weights)
                    if config.class_weights is not None
                    else None
                ),
                "checkpoint_provenance": checkpoint_provenance,
            }
            _save_checkpoint(
                model,
                tokenizer,
                checkpoints_dir / "last",
                torch=torch,
                optimizer=optimizer,
                scheduler=scheduler,
                trainer_state=trainer_state,
            )
            if improved:
                _save_checkpoint(
                    model,
                    tokenizer,
                    best_directory,
                    torch=torch,
                    optimizer=optimizer,
                    scheduler=scheduler,
                    trainer_state=trainer_state,
                )
            reporter.write(
                epoch_summary(
                    epoch=epoch,
                    total_epochs=config.epochs,
                    train_loss=train_loss,
                    validation=dict(validation),
                    learning_rate=learning_rate,
                    train_duration=format_duration(train_seconds),
                    validation_duration=format_duration(validation_seconds),
                    epoch_duration=format_duration(epoch_seconds),
                    best_macro_f1=best_score,
                    best_epoch=best_epoch,
                    checkpoint_updated=improved,
                    early_stopping_count=epochs_without_improvement,
                    early_stopping_patience=config.early_stopping_patience,
                )
            )
            if epochs_without_improvement >= config.early_stopping_patience:
                break
    except KeyboardInterrupt as exc:
        _save_checkpoint(
            model,
            tokenizer,
            checkpoints_dir / "interrupted",
            torch=torch,
            optimizer=optimizer,
            scheduler=scheduler,
            trainer_state={
                "completed_epoch": max(current_epoch - 1, 0),
                "best_epoch": best_epoch,
                "best_validation_macro_f1": best_score,
                "optimizer_step_count": optimizer_steps,
                "epochs_without_improvement": epochs_without_improvement,
                "history": history,
                "class_weights": (
                    list(config.class_weights)
                    if config.class_weights is not None
                    else None
                ),
                "checkpoint_provenance": checkpoint_provenance,
            },
        )
        raise TransformerTrainingError(
            "training was interrupted; an interrupt checkpoint was saved"
        ) from exc
    except RuntimeError as exc:
        if "out of memory" in str(exc).casefold():
            raise TransformerTrainingError(
                "accelerator memory was exhausted; reduce batch size or max_length"
            ) from exc
        raise TransformerTrainingError("transformer training failed") from exc
    if best_epoch == 0:
        raise TransformerTrainingError("no best validation checkpoint was selected")
    try:
        try:
            best_state = torch.load(
                best_load_directory / "pytorch_model.bin",
                map_location=device,
                weights_only=True,
            )
        except TypeError:  # pragma: no cover - older compatible torch
            best_state = torch.load(
                best_load_directory / "pytorch_model.bin", map_location=device
            )
        model.load_state_dict(best_state)
        model.to(device)
    except Exception as exc:
        raise TransformerTrainingError(
            "the best checkpoint could not be reloaded"
        ) from exc
    return TrainingResult(
        best_epoch=best_epoch,
        best_validation_macro_f1=best_score,
        history=tuple(history),
        stopped_early=len(history) < config.epochs,
        optimizer_step_count=optimizer_steps,
        total_elapsed_seconds=time.perf_counter() - fit_started,
    )


def evaluation_already_completed(state_path: Path) -> bool:
    """Return whether final evaluations were recorded in this output directory."""

    if not state_path.is_file():
        return False
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise TransformerTrainingError("the evaluation state file is invalid")
    return bool(
        isinstance(payload, Mapping) and payload.get("final_evaluation_completed")
    )
