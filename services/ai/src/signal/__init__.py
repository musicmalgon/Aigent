"""Rule-based signal combination interfaces."""

from .combine_signals import (
    AssessmentSignal,
    AssessmentSignalState,
    BehaviorSignal,
    BehaviorSignalState,
    EmotionSignal,
    EmotionSignalState,
    SignalAlignmentDirection,
    combine_signals,
)
from .reason_codes import ReasonCode

__all__ = [
    "AssessmentSignal",
    "AssessmentSignalState",
    "BehaviorSignal",
    "BehaviorSignalState",
    "EmotionSignal",
    "EmotionSignalState",
    "ReasonCode",
    "SignalAlignmentDirection",
    "combine_signals",
]
