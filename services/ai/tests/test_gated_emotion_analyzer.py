from __future__ import annotations

from types import SimpleNamespace

import pytest
from ai.src.emotion.base import PredictionExecutionError
from ai.src.emotion.gated_analyzer import NeutralGatedEmotionAnalyzer
from ai.src.emotion.neutral_gate import NeutralGateResult
from ai.src.schemas import (
    CoarseEmotionInput,
    NeutralGateDecision,
    RemindCoarseEmotionInferenceResponse,
    RemindCoarseEmotionLabel,
    RemindCoarseEmotionTopPrediction,
)


def _emotion_response() -> RemindCoarseEmotionInferenceResponse:
    probabilities = {
        RemindCoarseEmotionLabel.ANGER: 0.05,
        RemindCoarseEmotionLabel.JOY: 0.03,
        RemindCoarseEmotionLabel.ANXIETY: 0.70,
        RemindCoarseEmotionLabel.EMBARRASSMENT: 0.10,
        RemindCoarseEmotionLabel.SADNESS: 0.07,
        RemindCoarseEmotionLabel.LETHARGY: 0.05,
    }
    return RemindCoarseEmotionInferenceResponse(
        taxonomy_version="v2",
        model_version="emotion-v2",
        threshold_version="mvp-v1",
        predicted_emotion=RemindCoarseEmotionLabel.ANXIETY,
        predicted_label_id=2,
        emotion=RemindCoarseEmotionLabel.ANXIETY,
        confidence=0.70,
        margin=0.60,
        provisional=False,
        is_uncertain=False,
        uncertainty_reason=None,
        probabilities=probabilities,
        top_predictions=[
            RemindCoarseEmotionTopPrediction(
                emotion=RemindCoarseEmotionLabel.ANXIETY,
                label_id=2,
                probability=0.70,
            )
        ],
        latency_ms=2.0,
    )


class _Coarse:
    def __init__(self) -> None:
        self.is_loaded = True
        self.settings = SimpleNamespace(model_version="emotion-v2")
        self.predict_calls = 0

    def load(self) -> None:
        self.is_loaded = True

    def predict(
        self, request: CoarseEmotionInput
    ) -> RemindCoarseEmotionInferenceResponse:
        del request
        self.predict_calls += 1
        return _emotion_response()


class _Gate:
    def __init__(self, decision: NeutralGateDecision) -> None:
        self.is_loaded = True
        self.model_version = "neutral-gate-v1"
        self.decision = decision

    def load(self) -> None:
        self.is_loaded = True

    def predict(self, request: CoarseEmotionInput) -> NeutralGateResult:
        del request
        neutral_score = 0.8 if self.decision is NeutralGateDecision.NEUTRAL else 0.1
        return NeutralGateResult(
            decision=self.decision,
            neutral_score=neutral_score,
            emotional_score=1.0 - neutral_score,
            threshold=0.6,
            model_version="neutral-gate-v1",
            latency_ms=1.0,
        )


class _FailingGate(_Gate):
    def predict(self, request: CoarseEmotionInput) -> NeutralGateResult:
        del request
        raise PredictionExecutionError("synthetic gate failure")


def _request() -> CoarseEmotionInput:
    return CoarseEmotionInput(hs01="first", hs02="second")


def test_neutral_skips_six_class_and_returns_null_emotion_output() -> None:
    coarse = _Coarse()
    analyzer = NeutralGatedEmotionAnalyzer(
        coarse,  # type: ignore[arg-type]
        _Gate(NeutralGateDecision.NEUTRAL),  # type: ignore[arg-type]
    )
    result = analyzer.predict(_request())
    assert coarse.predict_calls == 0
    assert result.neutral_gate_decision is NeutralGateDecision.NEUTRAL
    assert result.predicted_emotion is None
    assert result.probabilities is None
    assert result.provisional is True
    assert analyzer.readiness_metadata == {
        "neutral_gate_enabled": True,
        "neutral_gate_model_version": "neutral-gate-v1",
    }


def test_emotional_invokes_existing_classifier_and_preserves_output() -> None:
    coarse = _Coarse()
    analyzer = NeutralGatedEmotionAnalyzer(
        coarse,  # type: ignore[arg-type]
        _Gate(NeutralGateDecision.EMOTIONAL),  # type: ignore[arg-type]
    )
    result = analyzer.predict(_request())
    assert coarse.predict_calls == 1
    assert result.neutral_gate_decision is NeutralGateDecision.EMOTIONAL
    assert result.predicted_emotion is RemindCoarseEmotionLabel.ANXIETY
    assert result.threshold_version == "mvp-v2-neutral-gate"
    assert result.latency_ms == 3.0


def test_gate_failure_does_not_fall_through_to_six_class_model() -> None:
    coarse = _Coarse()
    analyzer = NeutralGatedEmotionAnalyzer(
        coarse,  # type: ignore[arg-type]
        _FailingGate(NeutralGateDecision.NEUTRAL),  # type: ignore[arg-type]
    )
    with pytest.raises(PredictionExecutionError, match="synthetic gate failure"):
        analyzer.predict(_request())
    assert coarse.predict_calls == 0


def test_disabled_gate_reports_readiness_and_preserves_existing_pipeline() -> None:
    coarse = _Coarse()
    analyzer = NeutralGatedEmotionAnalyzer(coarse, None)  # type: ignore[arg-type]
    result = analyzer.predict(_request())
    assert coarse.predict_calls == 1
    assert result.neutral_gate_decision is None
    assert analyzer.readiness_metadata == {
        "neutral_gate_enabled": False,
        "neutral_gate_model_version": None,
    }
