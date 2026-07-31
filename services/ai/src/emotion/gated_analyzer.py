"""Composition layer for the neutral gate and six-class emotion analyzer."""

from __future__ import annotations

from ..schemas import (
    CoarseEmotionInput,
    RemindCoarseEmotionInferenceResponse,
    UncertaintyReason,
)
from .coarse_transformer import CoarseTransformerEmotionAnalyzer
from .neutral_gate import NeutralGateAnalyzer


class NeutralGatedEmotionAnalyzer:
    def __init__(
        self,
        coarse: CoarseTransformerEmotionAnalyzer,
        gate: NeutralGateAnalyzer | None,
        *,
        threshold_version: str = "mvp-v2-neutral-gate",
    ) -> None:
        self.coarse = coarse
        self.gate = gate
        self.threshold_version = threshold_version

    @property
    def gate_enabled(self) -> bool:
        return self.gate is not None

    @property
    def is_loaded(self) -> bool:
        return self.coarse.is_loaded and (self.gate is None or self.gate.is_loaded)

    @property
    def readiness_metadata(self) -> dict[str, object]:
        return {
            "neutral_gate_enabled": self.gate_enabled,
            "neutral_gate_model_version": (
                self.gate.model_version if self.gate is not None else None
            ),
        }

    def load(self) -> None:
        if self.gate is not None:
            self.gate.load()
        self.coarse.load()

    def predict(
        self,
        request: CoarseEmotionInput,
    ) -> RemindCoarseEmotionInferenceResponse:
        if self.gate is None:
            return self.coarse.predict(request)
        gate_result = self.gate.predict(request)
        if gate_result.decision.value == "neutral":
            return RemindCoarseEmotionInferenceResponse(
                taxonomy_version="v2",
                model_version=self.coarse.settings.model_version,
                threshold_version=self.threshold_version,
                predicted_emotion=None,
                predicted_label_id=None,
                emotion=None,
                confidence=None,
                margin=None,
                provisional=True,
                is_uncertain=True,
                uncertainty_reason=UncertaintyReason.NEUTRAL_GATE,
                probabilities=None,
                top_predictions=None,
                neutral_gate_decision=gate_result.decision,
                neutral_gate_score=gate_result.neutral_score,
                neutral_gate_model_version=gate_result.model_version,
                neutral_gate_threshold=gate_result.threshold,
                latency_ms=gate_result.latency_ms,
            )
        result = self.coarse.predict(request)
        payload = result.model_dump(mode="python")
        payload.update(
            threshold_version=self.threshold_version,
            neutral_gate_decision=gate_result.decision,
            neutral_gate_score=gate_result.neutral_score,
            neutral_gate_model_version=gate_result.model_version,
            neutral_gate_threshold=gate_result.threshold,
            latency_ms=result.latency_ms + gate_result.latency_ms,
        )
        return RemindCoarseEmotionInferenceResponse.model_validate(payload)


__all__ = ["NeutralGatedEmotionAnalyzer"]
