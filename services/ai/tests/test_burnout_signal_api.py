from __future__ import annotations

from ai.src.api import create_app
from ai.src.schemas import (
    BURNOUT_SIGNAL_LABELS,
    BurnoutSignalInferenceResponse,
    BurnoutSignalLabel,
    BurnoutSignalState,
    CoarseEmotionInput,
)
from fastapi.testclient import TestClient


class FakeCoarseService:
    def __init__(self) -> None:
        self.loaded = False

    @property
    def is_loaded(self) -> bool:
        return self.loaded

    def load(self) -> None:
        self.loaded = True

    def predict(self, request: CoarseEmotionInput) -> object:
        del request
        raise AssertionError("coarse inference is outside this test")


class FakeBurnoutSignalService:
    def __init__(self) -> None:
        self.loaded = False
        self.load_calls = 0

    @property
    def is_loaded(self) -> bool:
        return self.loaded

    def load(self) -> None:
        self.load_calls += 1
        self.loaded = True

    def predict(self, request: CoarseEmotionInput) -> BurnoutSignalInferenceResponse:
        del request
        probabilities = {label: 0.1 for label in BURNOUT_SIGNAL_LABELS}
        probabilities[BurnoutSignalLabel.EXHAUSTION] = 0.82
        return BurnoutSignalInferenceResponse(
            taxonomy_version="stage2-burnout-signals-v1",
            model_version="synthetic-multilabel-v1",
            threshold_version="synthetic-threshold-v1",
            probabilities=probabilities,
            thresholds={label: 0.7 for label in BURNOUT_SIGNAL_LABELS},
            signal_states={
                label: (
                    BurnoutSignalState.PRESENT
                    if label is BurnoutSignalLabel.EXHAUSTION
                    else BurnoutSignalState.UNVALIDATED
                )
                for label in BURNOUT_SIGNAL_LABELS
            },
            active_signals=[BurnoutSignalLabel.EXHAUSTION],
            validated_signals=[BurnoutSignalLabel.EXHAUSTION],
            deployment_status="partial",
            informational_only=True,
            risk_score_eligible=False,
            latency_ms=1.0,
        )


def test_signal_endpoint_is_separate_and_informational_only() -> None:
    signal_service = FakeBurnoutSignalService()
    with TestClient(
        create_app(
            analyzer=FakeCoarseService(),
            burnout_analyzer=signal_service,
        )
    ) as client:
        response = client.post(
            "/v1/burnout-signals/analyze",
            json={"hs01": "너무 지쳤다", "hs02": "오늘도 일이 많았다"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_signals"] == ["exhaustion"]
    assert payload["deployment_status"] == "partial"
    assert payload["informational_only"] is True
    assert payload["risk_score_eligible"] is False
    assert sum(payload["probabilities"].values()) != 1.0
    assert signal_service.load_calls == 1


def test_signal_endpoint_is_disabled_by_default() -> None:
    with TestClient(create_app(analyzer=FakeCoarseService())) as client:
        response = client.post(
            "/v1/burnout-signals/analyze",
            json={"hs01": "첫 문장", "hs02": "둘째 문장"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "burnout signal model is not ready"}
