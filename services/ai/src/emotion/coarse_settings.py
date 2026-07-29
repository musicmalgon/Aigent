"""Environment-backed settings for the coarse emotion inference service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TRAINING_MAX_LENGTH = 128
MVP_V1_CONFIDENCE_THRESHOLD = 0.65
MVP_V1_MARGIN_THRESHOLD = 0.15
MVP_V1_THRESHOLD_VERSION = "mvp-v1"


def _optional_path(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value.strip())


def _bounded_float(
    environment: Mapping[str, str], name: str, default: float
) -> float:
    raw = environment.get(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _bounded_int(
    environment: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = environment.get(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class CoarseEmotionSettings:
    artifact_dir: Path | None = None
    model_dir: Path | None = None
    tokenizer_dir: Path | None = None
    label_mapping_path: Path | None = None
    device: str = "auto"
    max_length: int = TRAINING_MAX_LENGTH
    confidence_threshold: float = MVP_V1_CONFIDENCE_THRESHOLD
    margin_threshold: float = MVP_V1_MARGIN_THRESHOLD
    threshold_version: str = MVP_V1_THRESHOLD_VERSION
    model_version: str = "klue-roberta-remind-coarse-v2"
    top_k: int = 2

    def __post_init__(self) -> None:
        if self.max_length != TRAINING_MAX_LENGTH:
            raise ValueError(
                f"EMOTION_MAX_LENGTH must match the training value "
                f"{TRAINING_MAX_LENGTH}"
            )
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if not 0.0 <= self.margin_threshold <= 1.0:
            raise ValueError("margin_threshold must be between 0 and 1")
        if not self.threshold_version.strip():
            raise ValueError("threshold_version must not be empty")
        if self.threshold_version == MVP_V1_THRESHOLD_VERSION and (
            self.confidence_threshold != MVP_V1_CONFIDENCE_THRESHOLD
            or self.margin_threshold != MVP_V1_MARGIN_THRESHOLD
        ):
            raise ValueError(
                "mvp-v1 requires confidence_threshold=0.65 and "
                "margin_threshold=0.15"
            )
        if not 1 <= self.top_k <= 6:
            raise ValueError("top_k must be between 1 and 6")
        if not self.model_version.strip():
            raise ValueError("model_version must not be empty")

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> CoarseEmotionSettings:
        values = os.environ if environment is None else environment
        model_version = values.get(
            "EMOTION_MODEL_VERSION", "klue-roberta-remind-coarse-v2"
        ).strip()
        if not model_version:
            raise ValueError("EMOTION_MODEL_VERSION must not be empty")
        threshold_version = values.get(
            "EMOTION_THRESHOLD_VERSION", MVP_V1_THRESHOLD_VERSION
        ).strip()
        if not threshold_version:
            raise ValueError("EMOTION_THRESHOLD_VERSION must not be empty")
        device = values.get("EMOTION_DEVICE", "auto").strip().casefold()
        if device not in {"auto", "cpu", "cuda", "mps"}:
            raise ValueError("EMOTION_DEVICE must be auto, cpu, cuda, or mps")
        return cls(
            artifact_dir=_optional_path(values.get("EMOTION_ARTIFACT_DIR")),
            model_dir=_optional_path(values.get("EMOTION_MODEL_DIR")),
            tokenizer_dir=_optional_path(values.get("EMOTION_TOKENIZER_DIR")),
            label_mapping_path=_optional_path(
                values.get("EMOTION_LABEL_MAPPING_PATH")
            ),
            device=device,
            max_length=_bounded_int(
                values,
                "EMOTION_MAX_LENGTH",
                TRAINING_MAX_LENGTH,
                minimum=2,
                maximum=4096,
            ),
            confidence_threshold=_bounded_float(
                values,
                "EMOTION_CONFIDENCE_THRESHOLD",
                MVP_V1_CONFIDENCE_THRESHOLD,
            ),
            margin_threshold=_bounded_float(
                values,
                "EMOTION_MARGIN_THRESHOLD",
                MVP_V1_MARGIN_THRESHOLD,
            ),
            threshold_version=threshold_version,
            model_version=model_version,
            top_k=_bounded_int(
                values,
                "EMOTION_TOP_K",
                2,
                minimum=1,
                maximum=6,
            ),
        )


__all__ = [
    "MVP_V1_CONFIDENCE_THRESHOLD",
    "MVP_V1_MARGIN_THRESHOLD",
    "MVP_V1_THRESHOLD_VERSION",
    "TRAINING_MAX_LENGTH",
    "CoarseEmotionSettings",
]
