"""Evaluation helpers for product-facing emotion model policies."""

from .abstention import (
    DEFAULT_CONFIDENCE_THRESHOLDS,
    DEFAULT_MARGIN_THRESHOLDS,
    NEUTRAL_LABEL,
    ScoredEmotionPrediction,
    calibration_bins,
    evaluate_threshold,
    threshold_grid,
)

__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLDS",
    "DEFAULT_MARGIN_THRESHOLDS",
    "NEUTRAL_LABEL",
    "ScoredEmotionPrediction",
    "calibration_bins",
    "evaluate_threshold",
    "threshold_grid",
]
