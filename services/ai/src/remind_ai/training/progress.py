"""tqdm progress reporting and human-readable training summaries."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any


@dataclass(frozen=True)
class ProgressConfig:
    enabled: bool = True
    update_interval: int = 1
    show_gpu_memory: bool = False


def format_duration(seconds: float) -> str:
    """Format a non-negative duration without losing its raw numeric value elsewhere."""

    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if remaining_seconds or not parts:
        parts.append(f"{remaining_seconds}s")
    return " ".join(parts)


class ProgressReporter:
    """Small wrapper that keeps tqdm behavior testable and logging consistent."""

    def __init__(self, config: ProgressConfig) -> None:
        if config.update_interval < 1:
            raise ValueError("progress update interval must be positive")
        self.config = config

    def batches(self, iterable: Any, *, total: int, desc: str) -> Any:
        tqdm = importlib.import_module("tqdm.auto").tqdm
        return tqdm(
            iterable,
            total=total,
            desc=desc,
            unit="batch",
            dynamic_ncols=True,
            leave=True,
            disable=not self.config.enabled,
        )

    def update_postfix(self, bar: Any, batch_index: int, values: dict[str, object]) -> None:
        if self.config.enabled and (
            batch_index % self.config.update_interval == 0
            or batch_index == getattr(bar, "total", None)
        ):
            bar.set_postfix(values, refresh=False)

    def write(self, message: str) -> None:
        if self.config.enabled:
            importlib.import_module("tqdm.auto").tqdm.write(message)
        else:
            print(message)

    def gpu_memory(self, torch: Any, device: Any) -> str | None:
        if (
            not self.config.show_gpu_memory
            or getattr(device, "type", str(device)) != "cuda"
            or not bool(torch.cuda.is_available())
        ):
            return None
        allocated = float(torch.cuda.memory_allocated(device)) / (1024**3)
        reserved = float(torch.cuda.memory_reserved(device)) / (1024**3)
        return f"{allocated:.1f}G/{reserved:.1f}G"


def epoch_summary(
    *,
    epoch: int,
    total_epochs: int,
    train_loss: float,
    validation: dict[str, object],
    learning_rate: float,
    train_duration: str,
    validation_duration: str,
    epoch_duration: str,
    best_macro_f1: float,
    best_epoch: int,
    checkpoint_updated: bool,
    early_stopping_count: int,
    early_stopping_patience: int,
) -> str:
    """Create a stable, readable epoch-end summary without snapshot coupling."""

    def metric(name: str) -> float:
        value = validation.get(name, 0.0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    separator = "=" * 60
    checkpoint = "updated" if checkpoint_updated else f"unchanged (epoch {best_epoch})"
    return "\n".join(
        (
            separator,
            f"Epoch {epoch}/{total_epochs} Summary",
            separator,
            f"Train loss       : {train_loss:.6f}",
            f"Validation loss  : {metric('loss'):.6f}",
            f"Accuracy         : {metric('accuracy'):.6f}",
            f"Macro precision  : {metric('macro_precision'):.6f}",
            f"Macro recall     : {metric('macro_recall'):.6f}",
            f"Macro F1         : {metric('macro_f1'):.6f}",
            f"Weighted F1      : {metric('weighted_f1'):.6f}",
            f"Learning rate    : {learning_rate:.2e}",
            f"Train time       : {train_duration}",
            f"Validation time  : {validation_duration}",
            f"Epoch time       : {epoch_duration}",
            f"Best macro F1    : {best_macro_f1:.6f}",
            f"Best checkpoint  : {checkpoint}",
            f"Early stopping   : {early_stopping_count}/{early_stopping_patience}",
            separator,
        )
    )
