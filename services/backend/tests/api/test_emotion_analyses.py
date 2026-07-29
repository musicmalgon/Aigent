from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import date, datetime
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
from app.services.baselines import calculate_and_store_baseline
from tests.daily_record_contract import canonical_daily_record_payload

BASE_PATH = "/api/v1/emotion-analyses"
DAILY_RECORD_PATH = "/api/v1/behavioral-records"
RECORD_DATE = "2026-07-20"
PASSWORD = "correct-horse-battery-staple"
Handler = Callable[[httpx.Request], httpx.Response]


def valid_ai_payload(
    probabilities: dict[CoarseEmotionLabel, float] | None = None,
) -> dict[str, Any]:
    probabilities = probabilities or {
        CoarseEmotionLabel.JOY: 0.05,
        CoarseEmotionLabel.ANXIETY: 0.55,
        CoarseEmotionLabel.EMBARRASSMENT: 0.12,
        CoarseEmotionLabel.ANGER: 0.08,
        CoarseEmotionLabel.SADNESS: 0.11,
        CoarseEmotionLabel.LETHARGY: 0.09,
    }
    labels = list(CoarseEmotionLabel)
    ordered = sorted(
        probabilities.items(),
        key=lambda item: (-item[1], labels.index(item[0])),
    )
    predicted_emotion, confidence = ordered[0]
    return {
        "model_version": "coarse-v1",
        "predicted_emotion": predicted_emotion.value,
        "predicted_label_id": labels.index(predicted_emotion),
        "confidence": confidence,
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


def authenticated_headers(
    client: TestClient,
    *,
    email: str = "emotion-analysis@example.com",
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
    return {"Authorization": f"Bearer {token}"}, cast(str, signup.json()["id"])


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
    assert body["model_version"] == "coarse-v1"
    assert body["predicted_emotion"] == CoarseEmotionLabel.ANXIETY.value
    assert body["confidence"] == 0.55
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
                CoarseEmotionLabel.ANXIETY: 0.55,
                CoarseEmotionLabel.EMBARRASSMENT: 0.1,
                CoarseEmotionLabel.ANGER: 0.1,
                CoarseEmotionLabel.SADNESS: 0.08,
                CoarseEmotionLabel.LETHARGY: 0.07,
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
        "model_version",
        "predicted_emotion",
        "confidence",
        "is_uncertain",
        "probabilities",
        "created_at",
    } == set(response_schema["properties"])
