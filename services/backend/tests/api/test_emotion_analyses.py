from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api import emotion_analyses as api_module
from app.clients.ai import (
    AIServiceClient,
    AIServiceClientConfig,
    CoarseEmotionLabel,
)
from app.core.config import Settings
from app.core.database import get_db
from app.main import create_app
from app.models.persistence import EmotionAnalysisResult
from app.repositories import emotion_results
from app.schemas.persistence import (
    EmotionLabel,
    EmotionResultCreate,
    EmotionTaxonomyVersion,
    EmotionV2Label,
)
from app.services.baselines import calculate_and_store_baseline
from tests.daily_record_contract import canonical_daily_record_payload

BASE_PATH = "/api/v1/emotion-analyses"
DAILY_RECORD_PATH = "/api/v1/behavioral-records"
CONSENTS_PATH = "/api/v1/consents"
RECORD_DATE = "2026-07-20"
PASSWORD = "correct-horse-battery-staple1!"
Handler = Callable[[httpx.Request], httpx.Response]


def valid_ai_payload(
    probabilities: dict[CoarseEmotionLabel, float] | None = None,
) -> dict[str, Any]:
    probabilities = probabilities or {
        CoarseEmotionLabel.JOY: 0.05,
        CoarseEmotionLabel.ANXIETY: 0.70,
        CoarseEmotionLabel.EMBARRASSMENT: 0.07,
        CoarseEmotionLabel.ANGER: 0.05,
        CoarseEmotionLabel.SADNESS: 0.07,
        CoarseEmotionLabel.LETHARGY: 0.06,
    }
    labels = list(CoarseEmotionLabel)
    ordered = sorted(
        probabilities.items(),
        key=lambda item: (-item[1], labels.index(item[0])),
    )
    predicted_emotion, confidence = ordered[0]
    margin = confidence - ordered[1][1]
    return {
        "taxonomy_version": "v2",
        "model_version": "coarse-v2",
        "threshold_version": "mvp-v1",
        "predicted_emotion": predicted_emotion.value,
        "predicted_label_id": labels.index(predicted_emotion),
        "emotion": predicted_emotion.value,
        "confidence": confidence,
        "margin": margin,
        "provisional": False,
        "is_uncertain": False,
        "uncertainty_reason": None,
        "probabilities": {
            label.value: probability for label, probability in probabilities.items()
        },
        "top_predictions": [
            {
                "emotion": label.value,
                "label_id": labels.index(label),
                "probability": probability,
            }
            for label, probability in ordered[:2]
        ],
        "latency_ms": 2.5,
    }


def json_response(
    request: httpx.Request,
    payload: object,
    *,
    status_code: int = 200,
) -> httpx.Response:
    return httpx.Response(status_code, request=request, json=payload)


@contextmanager
def emotion_api_client(
    settings: Settings,
    engine: Engine,
    handler: Handler,
    *,
    raise_server_exceptions: bool = True,
    observed_sessions: list[Session] | None = None,
) -> Generator[TestClient, None, None]:
    ai_client = AIServiceClient(
        AIServiceClientConfig.from_settings(settings),
        transport=httpx.MockTransport(handler),
    )
    application = create_app(settings, ai_service_client=ai_client)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            if observed_sessions is not None:
                observed_sessions.append(session)
            yield session

    application.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(
            application,
            raise_server_exceptions=raise_server_exceptions,
        ) as client:
            yield client
    finally:
        application.dependency_overrides.clear()
        asyncio.run(ai_client.aclose())


def grant_consent(
    client: TestClient,
    headers: dict[str, str],
    consent_type: str,
) -> None:
    response = client.post(
        CONSENTS_PATH,
        headers=headers,
        json={"consent_type": consent_type, "source": "test_setup"},
    )
    assert response.status_code == 201, response.text


def authenticated_headers(
    client: TestClient,
    *,
    email: str = "emotion-analysis@example.com",
    consents: tuple[str, ...] = ("health_data", "emotion_diary"),
) -> tuple[dict[str, str], str]:
    signup = client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200
    token = cast(str, login.json()["access_token"])
    headers = {"Authorization": f"Bearer {token}"}
    # 감정분석 POST는 emotion_diary 동의를, 선행 생활기록 등록은 health_data 동의를
    # 요구한다. 기본값으로 둘 다 부여해야 기존 테스트가 그대로 통과한다.
    for consent_type in consents:
        grant_consent(client, headers, consent_type)
    return headers, cast(str, signup.json()["id"])


def emotion_result_count(engine: Engine) -> int:
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(EmotionAnalysisResult)) or 0
        )


def create_daily_record(
    client: TestClient,
    headers: dict[str, str],
    *,
    record_date: str = RECORD_DATE,
) -> None:
    response = client.post(
        DAILY_RECORD_PATH,
        headers=headers,
        json=canonical_daily_record_payload(record_date=record_date),
    )
    assert response.status_code == 201, response.text


def test_requires_authentication(
    app_settings: Settings,
    migrated_engine: Engine,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(request, valid_ai_payload())

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        response = client.post(
            BASE_PATH,
            json={
                "record_date": RECORD_DATE,
                "hs01": "first",
                "hs02": "second",
            },
        )

    assert response.status_code == 401
    assert calls == 0
    assert emotion_result_count(migrated_engine) == 0


def test_create_without_emotion_diary_consent_is_forbidden(
    app_settings: Settings,
    migrated_engine: Engine,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(request, valid_ai_payload())

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        # health_data만 부여 — 선행 생활기록 등록은 되지만 감정분석은 막혀야 한다.
        headers, _ = authenticated_headers(client, consents=("health_data",))
        create_daily_record(client, headers)
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "first",
                "hs02": "second",
            },
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "emotion_diary 동의가 필요합니다"}
    assert calls == 0
    assert emotion_result_count(migrated_engine) == 0


def test_success_normalizes_request_and_returns_only_stored_result(
    app_settings: Settings,
    migrated_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    observed_request: dict[str, object] = {}
    observed_sessions: list[Session] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert observed_sessions
        assert observed_sessions[-1].in_transaction() is False
        observed_request.update(json.loads(request.content))
        return json_response(request, valid_ai_payload())

    with emotion_api_client(
        app_settings,
        migrated_engine,
        handler,
        observed_sessions=observed_sessions,
    ) as client:
        headers, user_id = authenticated_headers(client)
        create_daily_record(client, headers)
        with caplog.at_level(logging.INFO, logger="app.clients.ai"):
            response = client.post(
                BASE_PATH,
                headers=headers,
                json={
                    "record_date": RECORD_DATE,
                    "hs01": "  private   first text ",
                    "hs02": " private\nsecond text ",
                    "hs03": " \t ",
                },
            )

    assert response.status_code == 201, response.text
    body = response.json()
    assert observed_request == {
        "hs01": "private first text",
        "hs02": "private second text",
        "hs03": None,
    }
    assert body["user_id"] == user_id
    uuid.UUID(body["id"])
    uuid.UUID(body["user_id"])
    assert body["record_date"] == RECORD_DATE
    assert body["taxonomy_version"] == "v2"
    assert body["model_version"] == "coarse-v2"
    assert body["threshold_version"] == "mvp-v1"
    assert body["predicted_emotion"] == CoarseEmotionLabel.ANXIETY.value
    assert body["emotion"] == CoarseEmotionLabel.ANXIETY.value
    assert body["confidence"] == 0.70
    assert body["margin"] == pytest.approx(0.63)
    assert body["provisional"] is False
    assert body["is_uncertain"] is False
    assert body["probabilities"] == valid_ai_payload()["probabilities"]
    for field in ("analyzed_at", "created_at"):
        timestamp = datetime.fromisoformat(body[field].replace("Z", "+00:00"))
        assert timestamp.utcoffset() is not None
    assert {
        "input_hash",
        "predicted_label_id",
        "uncertainty_reason",
        "top_predictions",
        "latency_ms",
        "hs01",
        "hs02",
        "hs03",
    }.isdisjoint(body)
    assert "private" not in response.text
    assert "private" not in caplog.text

    with Session(migrated_engine) as session:
        stored = session.scalar(select(EmotionAnalysisResult))
        assert stored is not None
        assert stored.user_id == user_id
        assert stored.record_date == date.fromisoformat(RECORD_DATE)
        assert stored.taxonomy_version == "v2"
        assert stored.emotion == CoarseEmotionLabel.ANXIETY.value
        assert stored.provisional is False
        assert stored.threshold_version == "mvp-v1"
        assert stored.input_hash is None
        assert stored.probabilities == valid_ai_payload()["probabilities"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmotionAnalysisResult)
                .where(EmotionAnalysisResult.record_date.is_(None))
            )
            == 0
        )


def test_v2_abstention_is_saved_as_provenance_not_call_failure(
    app_settings: Settings,
    migrated_engine: Engine,
) -> None:
    probabilities = {
        CoarseEmotionLabel.ANGER: 0.05,
        CoarseEmotionLabel.JOY: 0.05,
        CoarseEmotionLabel.ANXIETY: 0.40,
        CoarseEmotionLabel.EMBARRASSMENT: 0.05,
        CoarseEmotionLabel.SADNESS: 0.35,
        CoarseEmotionLabel.LETHARGY: 0.10,
    }
    payload = valid_ai_payload(probabilities)
    payload.update(
        emotion=None,
        provisional=True,
        is_uncertain=True,
        uncertainty_reason="small_margin",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, payload)

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        headers, user_id = authenticated_headers(client)
        create_daily_record(client, headers)
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "오늘은 그냥 평범했다",
                "hs02": "특별한 일은 없었다",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user_id"] == user_id
    assert body["taxonomy_version"] == "v2"
    assert body["predicted_emotion"] == "불안"
    assert body["emotion"] is None
    assert body["confidence"] == 0.40
    assert body["margin"] == pytest.approx(0.05)
    assert body["provisional"] is True
    assert body["threshold_version"] == "mvp-v1"

    with Session(migrated_engine) as session:
        stored = session.scalar(select(EmotionAnalysisResult))
        assert stored is not None
        assert stored.predicted_emotion == "불안"
        assert stored.emotion is None
        assert stored.provisional is True
        assert stored.probabilities == {
            label.value: probability for label, probability in probabilities.items()
        }


def test_neutral_gate_result_is_persisted_without_emotion_signal(
    app_settings: Settings,
    migrated_engine: Engine,
) -> None:
    payload = {
        "taxonomy_version": "v2",
        "model_version": "coarse-v2-e25e28",
        "threshold_version": "mvp-v2-neutral-gate",
        "predicted_emotion": None,
        "predicted_label_id": None,
        "emotion": None,
        "confidence": None,
        "margin": None,
        "provisional": True,
        "is_uncertain": True,
        "uncertainty_reason": "neutral_gate",
        "probabilities": None,
        "top_predictions": None,
        "neutral_gate_decision": "neutral",
        "neutral_gate_score": 0.91,
        "neutral_gate_model_version": "neutral-gate-klue-roberta-v1",
        "neutral_gate_threshold": 0.62,
        "latency_ms": 2.5,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, payload)

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        headers, user_id = authenticated_headers(
            client,
            email="neutral-gate@example.com",
        )
        create_daily_record(client, headers)
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "오늘 오전에 수업에 갔어.",
                "hs02": "점심을 먹고 과제를 마쳤어.",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user_id"] == user_id
    assert body["predicted_emotion"] is None
    assert body["emotion"] is None
    assert body["confidence"] is None
    assert body["probabilities"] is None
    assert body["provisional"] is True
    assert body["neutral_gate_decision"] == "neutral"
    assert body["neutral_gate_score"] == pytest.approx(0.91)

    with Session(migrated_engine) as session:
        stored = session.scalar(select(EmotionAnalysisResult))
        assert stored is not None
        assert stored.predicted_emotion is None
        assert stored.probabilities is None
        assert stored.neutral_gate_decision == "neutral"
        assert stored.neutral_gate_model_version == "neutral-gate-klue-roberta-v1"


def test_missing_daily_record_returns_not_found_before_ai_call(
    app_settings: Settings,
    migrated_engine: Engine,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(request, valid_ai_payload())

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        headers, _ = authenticated_headers(client)
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "first",
                "hs02": "second",
            },
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Behavioral record not found."}
    assert calls == 0
    assert emotion_result_count(migrated_engine) == 0


def test_other_users_daily_record_returns_not_found_before_ai_call(
    app_settings: Settings,
    migrated_engine: Engine,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(request, valid_ai_payload())

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        owner_headers, _ = authenticated_headers(
            client,
            email="record-owner@example.com",
        )
        create_daily_record(client, owner_headers)
        other_headers, _ = authenticated_headers(
            client,
            email="analysis-owner@example.com",
        )
        response = client.post(
            BASE_PATH,
            headers=other_headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "first",
                "hs02": "second",
            },
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Behavioral record not found."}
    assert calls == 0
    assert emotion_result_count(migrated_engine) == 0


def test_future_record_date_is_rejected_before_lookup_and_ai_call(
    app_settings: Settings,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(request, valid_ai_payload())

    monkeypatch.setattr(
        api_module,
        "_utc_today",
        lambda: date(2026, 7, 20),
    )
    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        headers, _ = authenticated_headers(client)
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": "2026-07-21",
                "hs01": "first",
                "hs02": "second",
            },
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "record_date cannot be in the future."}
    assert calls == 0
    assert emotion_result_count(migrated_engine) == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"record_date": RECORD_DATE, "hs02": "second"},
        {"record_date": RECORD_DATE, "hs01": "first"},
        {"record_date": RECORD_DATE, "hs01": " ", "hs02": "second"},
        {"record_date": RECORD_DATE, "hs01": "first", "hs02": "\n"},
        {"hs01": "first", "hs02": "second"},
        {
            "record_date": RECORD_DATE,
            "hs01": "first",
            "hs02": "second",
            "unknown": "value",
        },
        {
            "record_date": RECORD_DATE,
            "hs01": "first",
            "hs02": "second",
            "user_id": "forged",
        },
        {
            "record_date": RECORD_DATE,
            "hs01": "x" * 2001,
            "hs02": "second",
        },
        {
            "record_date": RECORD_DATE,
            "hs01": "first",
            "hs02": "x" * 2001,
        },
    ],
)
def test_invalid_input_is_rejected_before_ai_call(
    app_settings: Settings,
    migrated_engine: Engine,
    payload: dict[str, object],
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(request, valid_ai_payload())

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        headers, _ = authenticated_headers(client)
        create_daily_record(client, headers)
        response = client.post(BASE_PATH, headers=headers, json=payload)

    assert response.status_code == 422
    assert calls == 0
    assert emotion_result_count(migrated_engine) == 0
    for value in payload.values():
        if isinstance(value, str) and value.strip():
            assert value not in response.text
    for error in response.json()["detail"]:
        assert set(error) == {"type", "loc", "msg"}


def test_two_thousand_character_boundary_is_accepted(
    app_settings: Settings,
    migrated_engine: Engine,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["hs01"] == "x" * 2000
        return json_response(request, valid_ai_payload())

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        headers, _ = authenticated_headers(client)
        create_daily_record(client, headers)
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "x" * 2000,
                "hs02": "second",
            },
        )

    assert response.status_code == 201


def test_repeated_analysis_is_append_only_and_baseline_uses_latest(
    app_settings: Settings,
    migrated_engine: Engine,
) -> None:
    calls = 0
    responses = [
        valid_ai_payload(
            {
                CoarseEmotionLabel.JOY: 0.8,
                CoarseEmotionLabel.ANXIETY: 0.05,
                CoarseEmotionLabel.EMBARRASSMENT: 0.04,
                CoarseEmotionLabel.ANGER: 0.04,
                CoarseEmotionLabel.SADNESS: 0.04,
                CoarseEmotionLabel.LETHARGY: 0.03,
            }
        ),
        valid_ai_payload(
            {
                CoarseEmotionLabel.JOY: 0.1,
                CoarseEmotionLabel.ANXIETY: 0.70,
                CoarseEmotionLabel.EMBARRASSMENT: 0.05,
                CoarseEmotionLabel.ANGER: 0.05,
                CoarseEmotionLabel.SADNESS: 0.05,
                CoarseEmotionLabel.LETHARGY: 0.05,
            }
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        response = responses[calls]
        calls += 1
        return json_response(request, response)

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        headers, user_id = authenticated_headers(client)
        create_daily_record(client, headers)
        first = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "same first",
                "hs02": "same second",
            },
        )
        second = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "same first",
                "hs02": "same second",
            },
        )

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["record_date"] == second.json()["record_date"] == RECORD_DATE
    assert calls == 2
    assert emotion_result_count(migrated_engine) == 2
    with Session(migrated_engine) as session:
        baseline = calculate_and_store_baseline(
            session,
            user_id=user_id,
            window_end=date.fromisoformat(RECORD_DATE),
            today=date.fromisoformat(RECORD_DATE),
        )
        assert baseline.negative_emotion_probability == 0.9
        assert baseline.sample_days == 1


def test_history_serializes_mixed_v1_and_v2_taxonomies(
    app_settings: Settings,
    migrated_engine: Engine,
) -> None:
    def unused_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected AI request: {request.url}")

    with emotion_api_client(
        app_settings,
        migrated_engine,
        unused_handler,
    ) as client:
        headers, user_id = authenticated_headers(client)
        with Session(migrated_engine) as session:
            v1 = emotion_results.create_emotion_result(
                session,
                user_id=user_id,
                payload=EmotionResultCreate(
                    record_date=date(2026, 7, 19),
                    analyzed_at=datetime(2026, 7, 19, 9, tzinfo=UTC),
                    model_version="legacy-v1",
                    predicted_emotion=EmotionLabel.HURT,
                    confidence=0.7,
                    is_uncertain=True,
                    probabilities={
                        EmotionLabel.JOY: 0.05,
                        EmotionLabel.ANXIETY: 0.05,
                        EmotionLabel.EMBARRASSMENT: 0.05,
                        EmotionLabel.ANGER: 0.05,
                        EmotionLabel.SADNESS: 0.10,
                        EmotionLabel.HURT: 0.70,
                    },
                ),
            )
            v2 = emotion_results.create_emotion_result(
                session,
                user_id=user_id,
                payload=EmotionResultCreate(
                    record_date=date(2026, 7, 20),
                    analyzed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
                    taxonomy_version=EmotionTaxonomyVersion.V2,
                    model_version="coarse-v2",
                    predicted_emotion=EmotionV2Label.LETHARGY,
                    emotion=EmotionV2Label.LETHARGY,
                    confidence=0.70,
                    margin=0.60,
                    provisional=False,
                    is_uncertain=False,
                    probabilities={
                        EmotionV2Label.ANGER: 0.05,
                        EmotionV2Label.JOY: 0.05,
                        EmotionV2Label.ANXIETY: 0.05,
                        EmotionV2Label.EMBARRASSMENT: 0.05,
                        EmotionV2Label.SADNESS: 0.10,
                        EmotionV2Label.LETHARGY: 0.70,
                    },
                    threshold_version="mvp-v1",
                ),
            )
            session.commit()
            v1_id = v1.id
            v2_id = v2.id

        history = client.get(BASE_PATH, headers=headers)
        latest = client.get(f"{BASE_PATH}/latest", headers=headers)
        legacy = client.get(f"{BASE_PATH}/{v1_id}", headers=headers)

    assert history.status_code == latest.status_code == legacy.status_code == 200
    rows = history.json()
    assert [row["id"] for row in rows] == [v2_id, v1_id]
    assert rows[0]["taxonomy_version"] == "v2"
    assert rows[0]["emotion"] == "무기력"
    assert rows[1]["taxonomy_version"] == "v1"
    assert rows[1]["emotion"] == "상처"
    assert latest.json()["id"] == v2_id
    assert legacy.json()["predicted_emotion"] == "상처"


@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("connection", 503),
        ("connect_timeout", 504),
        ("read_timeout", 504),
        ("downstream_4xx", 502),
        ("downstream_5xx", 502),
        ("invalid_json", 502),
        ("invalid_schema", 502),
    ],
)
def test_downstream_failures_are_safe_and_do_not_write(
    app_settings: Settings,
    migrated_engine: Engine,
    case: str,
    expected_status: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_text = "private-emotion-input"

    def handler(request: httpx.Request) -> httpx.Response:
        if case == "connection":
            raise httpx.ConnectError("private downstream detail", request=request)
        if case == "connect_timeout":
            raise httpx.ConnectTimeout(
                "private downstream detail",
                request=request,
            )
        if case == "read_timeout":
            raise httpx.ReadTimeout(
                "private downstream detail",
                request=request,
            )
        if case == "downstream_4xx":
            return json_response(
                request,
                {"detail": sensitive_text},
                status_code=422,
            )
        if case == "downstream_5xx":
            return json_response(
                request,
                {"detail": sensitive_text},
                status_code=503,
            )
        if case == "invalid_json":
            return httpx.Response(
                200,
                request=request,
                content=b"not-json-private-body",
            )
        return json_response(request, {"private": sensitive_text})

    with emotion_api_client(app_settings, migrated_engine, handler) as client:
        headers, _ = authenticated_headers(client)
        create_daily_record(client, headers)
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": sensitive_text,
                "hs02": "second",
            },
        )

    assert response.status_code == expected_status
    assert sensitive_text not in response.text
    assert "private downstream detail" not in response.text
    assert "not-json-private-body" not in response.text
    assert sensitive_text not in caplog.text
    assert "private downstream detail" not in caplog.text
    assert "not-json-private-body" not in caplog.text
    assert emotion_result_count(migrated_engine) == 0


def test_repository_failure_rolls_back_without_partial_write(
    app_settings: Settings,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, valid_ai_payload())

    def fail_repository(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("private database detail")

    monkeypatch.setattr(
        emotion_results,
        "create_emotion_result",
        fail_repository,
    )
    with emotion_api_client(
        app_settings,
        migrated_engine,
        handler,
        raise_server_exceptions=False,
    ) as client:
        headers, _ = authenticated_headers(client)
        create_daily_record(client, headers)
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "private input",
                "hs02": "second",
            },
        )

    assert response.status_code == 500
    assert "private" not in response.text
    assert emotion_result_count(migrated_engine) == 0


def test_commit_failure_rolls_back_without_partial_write(
    app_settings: Settings,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, valid_ai_payload())

    with emotion_api_client(
        app_settings,
        migrated_engine,
        handler,
        raise_server_exceptions=False,
    ) as client:
        headers, _ = authenticated_headers(client)
        create_daily_record(client, headers)

        def fail_commit(session: Session) -> None:
            raise SQLAlchemyError("private commit detail")

        monkeypatch.setattr(Session, "commit", fail_commit)
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={
                "record_date": RECORD_DATE,
                "hs01": "private input",
                "hs02": "second",
            },
        )

    assert response.status_code == 500
    assert "private" not in response.text
    assert emotion_result_count(migrated_engine) == 0


def test_openapi_declares_minimal_authenticated_contract(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    operation = schema["paths"][BASE_PATH]["post"]
    request_ref = operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    response_ref = operation["responses"]["201"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[1]]
    response_schema = schema["components"]["schemas"][response_ref.rsplit("/", 1)[1]]

    assert operation["security"]
    assert set(request_schema["required"]) == {"record_date", "hs01", "hs02"}
    assert set(request_schema["properties"]) == {
        "record_date",
        "hs01",
        "hs02",
        "hs03",
    }
    assert request_schema["additionalProperties"] is False
    assert {"user_id", "input_hash"}.isdisjoint(request_schema["properties"])
    assert {
        "id",
        "user_id",
        "record_date",
        "analyzed_at",
        "taxonomy_version",
        "model_version",
        "predicted_emotion",
        "emotion",
        "confidence",
        "margin",
        "provisional",
        "is_uncertain",
        "probabilities",
        "threshold_version",
        "neutral_gate_decision",
        "neutral_gate_score",
        "neutral_gate_model_version",
        "neutral_gate_threshold",
        "created_at",
    } == set(response_schema["properties"])
