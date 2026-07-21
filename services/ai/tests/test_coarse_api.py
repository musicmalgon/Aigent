"""API boundary tests using a tiny in-memory coarse emotion service."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ai.src.api import create_app
from ai.src.emotion.base import (
    ModelArtifactNotConfiguredError,
    PredictionExecutionError,
)
from ai.src.schemas import (
    CoarseEmotionInferenceResponse,
    CoarseEmotionInput,
    CoarseEmotionLabel,
    CoarseEmotionTopPrediction,
)


def _response() -> CoarseEmotionInferenceResponse:
    probabilities = {
        CoarseEmotionLabel.JOY: 0.03,
        CoarseEmotionLabel.ANXIETY: 0.54,
        CoarseEmotionLabel.EMBARRASSMENT: 0.14,
        CoarseEmotionLabel.ANGER: 0.08,
        CoarseEmotionLabel.SADNESS: 0.13,
        CoarseEmotionLabel.HURT: 0.08,
    }
    return CoarseEmotionInferenceResponse(
        model_version="synthetic-coarse-v1",
        predicted_emotion=CoarseEmotionLabel.ANXIETY,
        predicted_label_id=1,
        confidence=0.54,
        is_uncertain=False,
        uncertainty_reason=None,
        probabilities=probabilities,
        top_predictions=[
            CoarseEmotionTopPrediction(
                emotion=CoarseEmotionLabel.ANXIETY,
                label_id=1,
                probability=0.54,
            ),
            CoarseEmotionTopPrediction(
                emotion=CoarseEmotionLabel.EMBARRASSMENT,
                label_id=2,
                probability=0.14,
            ),
        ],
        latency_ms=1.5,
    )


class _FakeService:
    def __init__(
        self,
        *,
        load_error: Exception | None = None,
        predict_error: Exception | None = None,
    ) -> None:
        self.loaded = False
        self.load_error = load_error
        self.predict_error = predict_error
        self.load_calls = 0
        self.predict_calls = 0

    @property
    def is_loaded(self) -> bool:
        return self.loaded

    def load(self) -> None:
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error
        self.loaded = True

    def predict(self, request: CoarseEmotionInput) -> CoarseEmotionInferenceResponse:
        del request
        self.predict_calls += 1
        if self.predict_error is not None:
            raise self.predict_error
        return _response()


def test_endpoint_success_and_model_is_loaded_once() -> None:
    service = _FakeService()
    with TestClient(create_app(analyzer=service)) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ready"}
        response = client.post(
            "/v1/emotions/classify",
            json={"hs01": "합성 첫 문장", "hs02": "합성 두 번째 문장", "hs03": None},
        )
        second = client.post(
            "/v1/emotions/classify",
            json={"hs01": "다른 첫 문장", "hs02": "다른 두 번째 문장"},
        )

    assert response.status_code == 200
    assert second.status_code == 200
    payload = response.json()
    assert payload["predicted_emotion"] == "불안"
    assert len(payload["probabilities"]) == 6
    assert sum(payload["probabilities"].values()) == 1.0
    assert service.load_calls == 1
    assert service.predict_calls == 2


def test_missing_model_keeps_liveness_but_fails_readiness() -> None:
    service = _FakeService(
        load_error=ModelArtifactNotConfiguredError("synthetic missing model")
    )
    with TestClient(create_app(analyzer=service)) as client:
        assert client.get("/health/live").status_code == 200
        readiness = client.get("/health/ready")
        inference = client.post(
            "/v1/emotions/classify",
            json={"hs01": "합성 첫 문장", "hs02": "합성 두 번째 문장"},
        )
    assert readiness.status_code == 503
    assert readiness.json() == {"status": "not_ready"}
    assert inference.status_code == 503


def test_inference_error_is_generic_and_empty_input_is_rejected() -> None:
    service = _FakeService(
        predict_error=PredictionExecutionError("private synthetic backend detail")
    )
    with TestClient(create_app(analyzer=service)) as client:
        failure = client.post(
            "/v1/emotions/classify",
            json={"hs01": "합성 첫 문장", "hs02": "합성 두 번째 문장"},
        )
        invalid = client.post(
            "/v1/emotions/classify",
            json={"hs01": " ", "hs02": "합성 두 번째 문장"},
        )
    assert failure.status_code == 500
    assert failure.json() == {"detail": "emotion inference failed"}
    assert "private synthetic backend detail" not in failure.text
    assert invalid.status_code == 422
