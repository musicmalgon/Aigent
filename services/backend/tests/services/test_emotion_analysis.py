from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import date
from typing import Any, TypeVar, cast

import pytest
from sqlalchemy.orm import Session

from app.clients.ai import (
    AIServiceClient,
    AIServiceConnectionError,
    BurnoutSignalResponse,
    BurnoutSignalState,
    CoarseEmotionLabel,
    CoarseEmotionRequest,
    CoarseEmotionResponse,
    CoarseEmotionTopPrediction,
    UncertaintyReason,
)
from app.models.persistence import EmotionAnalysisResult
from app.repositories import emotion_results
from app.schemas.persistence import (
    EmotionResultCreate,
    EmotionTaxonomyVersion,
    EmotionV2Label,
)
from app.services.emotion_analysis import (
    analyze_and_stage_emotion_result,
    map_ai_response_to_persistence,
)

Result = TypeVar("Result")


def run(coroutine: Coroutine[Any, Any, Result]) -> Result:
    return asyncio.run(coroutine)


def ai_response() -> CoarseEmotionResponse:
    probabilities = {
        CoarseEmotionLabel.JOY: 0.05,
        CoarseEmotionLabel.ANXIETY: 0.55,
        CoarseEmotionLabel.EMBARRASSMENT: 0.12,
        CoarseEmotionLabel.ANGER: 0.08,
        CoarseEmotionLabel.SADNESS: 0.11,
        CoarseEmotionLabel.LETHARGY: 0.09,
    }
    return CoarseEmotionResponse(
        taxonomy_version="v2",
        model_version="coarse-v2",
        threshold_version="mvp-v1",
        predicted_emotion=CoarseEmotionLabel.ANXIETY,
        predicted_label_id=2,
        emotion=None,
        confidence=0.55,
        margin=0.43,
        provisional=True,
        is_uncertain=True,
        uncertainty_reason=UncertaintyReason.LOW_CONFIDENCE,
        probabilities=probabilities,
        top_predictions=[
            CoarseEmotionTopPrediction(
                emotion=label,
                label_id=list(CoarseEmotionLabel).index(label),
                probability=probability,
            )
            for label, probability in sorted(
                probabilities.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        latency_ms=12.5,
    )


class FakeAIClient:
    def __init__(
        self,
        response: CoarseEmotionResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[CoarseEmotionRequest] = []
        self.burnout_response: BurnoutSignalResponse | None = None
        self.stage2_burnout_signals_enabled = False

    async def classify_emotion(
        self,
        request: CoarseEmotionRequest,
    ) -> CoarseEmotionResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response

    async def analyze_burnout_signals(
        self,
        request: CoarseEmotionRequest,
    ) -> BurnoutSignalResponse | None:
        del request
        return self.burnout_response


def test_mapping_contains_only_persistence_fields() -> None:
    response = ai_response()
    record_date = date(2026, 7, 20)

    payload = map_ai_response_to_persistence(
        response,
        record_date=record_date,
    )
    stored = payload.model_dump(mode="json")

    assert payload.record_date == record_date
    assert payload.model_version == response.model_version
    assert payload.taxonomy_version is EmotionTaxonomyVersion.V2
    assert payload.predicted_emotion is EmotionV2Label.ANXIETY
    assert payload.emotion is None
    assert payload.confidence == response.confidence
    assert payload.margin == response.margin
    assert payload.provisional is True
    assert payload.threshold_version == "mvp-v1"
    assert payload.is_uncertain is True
    assert payload.input_hash is None
    assert payload.analyzed_at.utcoffset() is not None
    assert payload.probabilities is not None
    assert response.probabilities is not None
    assert set(payload.probabilities) == set(EmotionV2Label)
    assert {
        label.value: probability
        for label, probability in payload.probabilities.items()
    } == {
        label.value: probability
        for label, probability in response.probabilities.items()
    }
    assert {
        "predicted_label_id",
        "uncertainty_reason",
        "top_predictions",
        "latency_ms",
        "hs01",
        "hs02",
        "hs03",
    }.isdisjoint(stored)


def test_orchestration_forwards_normalized_request_and_user_id(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = CoarseEmotionRequest(
        hs01="  first   private input ",
        hs02=" second\nprivate input ",
        hs03=" \t ",
    )
    record_date = date(2026, 7, 20)
    fake_client = FakeAIClient(response=ai_response())
    captured: dict[str, object] = {}
    sentinel = cast(EmotionAnalysisResult, object())

    def capture_result(
        session: Session,
        *,
        user_id: str,
        payload: EmotionResultCreate,
    ) -> EmotionAnalysisResult:
        captured.update(
            session=session,
            user_id=user_id,
            payload=payload,
        )
        return sentinel

    monkeypatch.setattr(
        emotion_results,
        "create_emotion_result",
        capture_result,
    )

    result = run(
        analyze_and_stage_emotion_result(
            db_session,
            user_id="authenticated-user",
            record_date=record_date,
            request=request,
            ai_client=cast(AIServiceClient, fake_client),
        )
    )

    assert result is sentinel
    assert fake_client.requests == [request]
    assert request.hs01 == "first private input"
    assert request.hs02 == "second private input"
    assert request.hs03 is None
    assert captured["session"] is db_session
    assert captured["user_id"] == "authenticated-user"
    payload = cast(EmotionResultCreate, captured["payload"])
    assert payload.record_date == record_date
    assert payload.input_hash is None
    assert "private input" not in repr(payload)


def test_orchestration_persists_structured_stage2_provenance(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeAIClient(response=ai_response())
    fake_client.stage2_burnout_signals_enabled = True
    labels = {
        "exhaustion": 0.9,
        "overload": 0.1,
        "helplessness": 0.1,
        "low_efficacy": 0.1,
        "anxiety": 0.1,
        "irritability": 0.1,
    }
    fake_client.burnout_response = BurnoutSignalResponse(
        taxonomy_version="stage2-burnout-signals-v1",
        model_version="stage2-test",
        threshold_version="stage2-test-thresholds",
        probabilities=labels,
        thresholds={label: 0.65 for label in labels},
        signal_states={
            label: (
                BurnoutSignalState.PRESENT
                if label == "exhaustion"
                else BurnoutSignalState.UNVALIDATED
            )
            for label in labels
        },
        active_signals=["exhaustion"],
        validated_signals=["exhaustion"],
        deployment_status="partial",
        informational_only=True,
        risk_score_eligible=False,
        latency_ms=1.0,
    )
    captured: dict[str, object] = {}

    def capture_result(
        session: Session,
        *,
        user_id: str,
        payload: EmotionResultCreate,
    ) -> EmotionAnalysisResult:
        del session
        captured.update(user_id=user_id, payload=payload)
        return cast(EmotionAnalysisResult, object())

    monkeypatch.setattr(emotion_results, "create_emotion_result", capture_result)
    run(
        analyze_and_stage_emotion_result(
            db_session,
            user_id="authenticated-user",
            record_date=date(2026, 7, 20),
            request=CoarseEmotionRequest(hs01="first", hs02="second"),
            ai_client=cast(AIServiceClient, fake_client),
        )
    )

    payload = cast(EmotionResultCreate, captured["payload"])
    assert payload.burnout_signal_payload is not None
    assert payload.burnout_signal_payload["active_signals"] == ["exhaustion"]


def test_ai_failure_does_not_call_repository(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        emotion_results,
        "create_emotion_result",
        fail_if_called,
    )
    fake_client = FakeAIClient(
        error=AIServiceConnectionError(
            "AI service connection failed",
            endpoint="v2/emotions/classify",
            error_code="downstream_connection_failure",
        )
    )

    with pytest.raises(AIServiceConnectionError):
        run(
            analyze_and_stage_emotion_result(
                db_session,
                user_id="authenticated-user",
                record_date=date(2026, 7, 20),
                request=CoarseEmotionRequest(hs01="first", hs02="second"),
                ai_client=cast(AIServiceClient, fake_client),
            )
        )

    assert called is False
