from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Generator
from datetime import date, datetime
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.api import behavioral_records as api_module
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models.user import User
from app.repositories import behavioral_records as repository_module

BASE_PATH = "/api/v1/behavioral-records"
PASSWORD = "correct-horse-battery-staple"


def authenticated_user(
    client: TestClient,
    *,
    email: str = "daily-record@example.com",
) -> tuple[dict[str, str], dict[str, object]]:
    signup_response = client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD},
    )
    assert signup_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login_response.status_code == 200
    token = cast(str, login_response.json()["access_token"])
    return (
        {"Authorization": f"Bearer {token}"},
        cast(dict[str, object], signup_response.json()),
    )


def create_record(
    client: TestClient,
    headers: dict[str, str],
    record_date: str,
    **fields: object,
) -> dict[str, object]:
    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"record_date": record_date, **fields},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_create_requires_authentication(client: TestClient) -> None:
    response = client.post(BASE_PATH, json={"record_date": "2026-07-20"})

    assert response.status_code == 401


def test_create_full_record_and_serialize_response(client: TestClient) -> None:
    headers, user = authenticated_user(client)

    body = create_record(
        client,
        headers,
        "2026-07-20",
        sleep_minutes=420,
        study_work_minutes=480,
        rest_minutes=60,
        exercise_minutes=30,
        schedule_count=5,
        subjective_stress=4.5,
        subjective_fatigue=6.0,
        source="manual",
        timezone="Asia/Seoul",
        data_completeness=0.9,
    )

    uuid.UUID(cast(str, body["id"]))
    uuid.UUID(cast(str, body["user_id"]))
    assert body["user_id"] == user["id"]
    assert body["record_date"] == "2026-07-20"
    assert body["study_work_minutes"] == 480
    assert body["timezone"] == "Asia/Seoul"
    assert body["data_completeness"] == 0.9
    for field in ("created_at", "updated_at"):
        serialized = cast(str, body[field]).replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(serialized)
        assert timestamp.utcoffset() is not None


def test_create_preserves_nulls_and_optional_defaults(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    explicit_nulls = create_record(
        client,
        headers,
        "2026-07-19",
        sleep_minutes=None,
        study_work_minutes=None,
        rest_minutes=None,
        exercise_minutes=None,
        schedule_count=None,
        subjective_stress=None,
        subjective_fatigue=None,
        data_completeness=None,
    )
    omitted = create_record(client, headers, "2026-07-18")

    nullable_fields = (
        "sleep_minutes",
        "study_work_minutes",
        "rest_minutes",
        "exercise_minutes",
        "schedule_count",
        "subjective_stress",
        "subjective_fatigue",
        "data_completeness",
    )
    assert all(explicit_nulls[field] is None for field in nullable_fields)
    assert all(omitted[field] is None for field in nullable_fields)
    assert omitted["source"] == "manual"
    assert omitted["timezone"] == "UTC"


def test_client_cannot_set_user_id_or_unknown_fields(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    for extra in ({"user_id": str(uuid.uuid4())}, {"unexpected": "value"}):
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={"record_date": "2026-07-20", **extra},
        )
        assert response.status_code == 422

    assert client.get(
        f"{BASE_PATH}/2026-07-20",
        headers=headers,
    ).status_code == 404


def test_duplicate_user_date_returns_conflict_and_recovers(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client)
    create_record(client, headers, "2026-07-20")

    duplicate = client.post(
        BASE_PATH,
        headers=headers,
        json={"record_date": "2026-07-20"},
    )

    assert duplicate.status_code == 409
    assert "constraint" not in duplicate.text.lower()
    assert "behavioral_daily_records" not in duplicate.text
    create_record(client, headers, "2026-07-19")


def test_different_users_can_create_the_same_date(client: TestClient) -> None:
    first_headers, first_user = authenticated_user(
        client,
        email="first@example.com",
    )
    second_headers, second_user = authenticated_user(
        client,
        email="second@example.com",
    )

    first = create_record(client, first_headers, "2026-07-20")
    second = create_record(client, second_headers, "2026-07-20")

    assert first["user_id"] == first_user["id"]
    assert second["user_id"] == second_user["id"]
    assert first["id"] != second["id"]


def test_read_record_by_date(client: TestClient) -> None:
    headers, _ = authenticated_user(client)
    created = create_record(
        client,
        headers,
        "2026-07-20",
        sleep_minutes=480,
    )

    response = client.get(f"{BASE_PATH}/2026-07-20", headers=headers)

    assert response.status_code == 200
    assert response.json() == created


def test_read_missing_and_invalid_dates(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    assert client.get(
        f"{BASE_PATH}/2026-07-20",
        headers=headers,
    ).status_code == 404
    assert client.get(
        f"{BASE_PATH}/not-a-date",
        headers=headers,
    ).status_code == 422


def test_records_are_isolated_between_users(client: TestClient) -> None:
    owner_headers, _ = authenticated_user(client, email="owner@example.com")
    other_headers, _ = authenticated_user(client, email="other@example.com")
    create_record(client, owner_headers, "2026-07-20")

    assert client.get(
        f"{BASE_PATH}/2026-07-20",
        headers=other_headers,
    ).status_code == 404
    response = client.get(
        BASE_PATH,
        headers=other_headers,
        params={"date_from": "2026-07-20", "date_to": "2026-07-20"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_range_is_inclusive_and_uses_repository_order(client: TestClient) -> None:
    headers, _ = authenticated_user(client)
    for record_date in (
        "2026-06-30",
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-04",
    ):
        create_record(client, headers, record_date)

    response = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_from": "2026-07-01", "date_to": "2026-07-03"},
    )

    assert response.status_code == 200
    assert [item["record_date"] for item in response.json()] == [
        "2026-07-03",
        "2026-07-02",
        "2026-07-01",
    ]


def test_default_range_contains_latest_14_utc_days(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = authenticated_user(client)
    monkeypatch.setattr(api_module, "_utc_today", lambda: date(2026, 7, 20))
    for record_date in ("2026-07-06", "2026-07-07", "2026-07-20"):
        create_record(client, headers, record_date)

    response = client.get(BASE_PATH, headers=headers)

    assert response.status_code == 200
    assert [item["record_date"] for item in response.json()] == [
        "2026-07-20",
        "2026-07-07",
    ]


@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [
        ("2026-07-20", "2026-07-19"),
        ("2026-07-01", "2026-07-29"),
        ("2026-07-01", None),
        (None, "2026-07-20"),
    ],
)
def test_invalid_or_excessive_range_is_rejected(
    client: TestClient,
    date_from: str | None,
    date_to: str | None,
) -> None:
    headers, _ = authenticated_user(client)

    response = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_from": date_from, "date_to": date_to},
    )

    assert response.status_code == 422


def test_28_day_range_is_allowed(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    response = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_from": "2026-07-01", "date_to": "2026-07-28"},
    )

    assert response.status_code == 200


def test_numeric_boundaries_are_accepted(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    body = create_record(
        client,
        headers,
        "2026-07-20",
        sleep_minutes=0,
        study_work_minutes=1440,
        rest_minutes=0,
        exercise_minutes=1440,
        schedule_count=0,
        subjective_stress=0,
        subjective_fatigue=10,
        data_completeness=1,
    )

    assert body["sleep_minutes"] == 0
    assert body["study_work_minutes"] == 1440
    assert body["subjective_fatigue"] == 10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sleep_minutes", -1),
        ("sleep_minutes", 1441),
        ("study_work_minutes", 1441),
        ("rest_minutes", -1),
        ("exercise_minutes", 1441),
        ("schedule_count", -1),
        ("subjective_stress", 10.1),
        ("subjective_fatigue", -0.1),
        ("data_completeness", 1.1),
        ("timezone", "not/a/real-zone"),
        ("source", "untrusted"),
    ],
)
def test_invalid_payload_is_rejected_without_write(
    client: TestClient,
    field: str,
    value: object,
) -> None:
    headers, _ = authenticated_user(client)

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"record_date": "2026-07-20", field: value},
    )

    assert response.status_code == 422
    assert client.get(
        f"{BASE_PATH}/2026-07-20",
        headers=headers,
    ).status_code == 404


def test_future_date_uses_submitted_timezone(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = authenticated_user(client)
    observed_timezones: list[str] = []

    def local_today(timezone_name: str) -> date:
        observed_timezones.append(timezone_name)
        return date(2026, 7, 20)

    monkeypatch.setattr(api_module, "_today_in_timezone", local_today)

    accepted = client.post(
        BASE_PATH,
        headers=headers,
        json={"record_date": "2026-07-20", "timezone": "Asia/Seoul"},
    )
    rejected = client.post(
        BASE_PATH,
        headers=headers,
        json={"record_date": "2026-07-21", "timezone": "America/New_York"},
    )

    assert accepted.status_code == 201
    assert rejected.status_code == 422
    assert observed_timezones == ["Asia/Seoul", "America/New_York"]


def test_database_unique_race_is_returned_as_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = authenticated_user(client)
    create_record(client, headers, "2026-07-20")
    monkeypatch.setattr(
        repository_module,
        "get_daily_record_by_date",
        lambda *args, **kwargs: None,
    )

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"record_date": "2026-07-20"},
    )

    assert response.status_code == 409


def test_unrelated_integrity_error_is_not_a_duplicate() -> None:
    error = IntegrityError(
        "INSERT",
        {},
        sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
    )

    assert api_module._is_daily_record_unique_violation(error) is False


def test_duplicate_rolls_back_shared_session(
    test_app: FastAPI,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="shared-session@example.com",
        hashed_password=hash_password(PASSWORD),
    )
    db_session.add(user)
    db_session.commit()
    headers = {
        "Authorization": f"Bearer {create_access_token(subject=user.id)}"
    }

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    test_app.dependency_overrides[get_db] = override_get_db
    rollback = Mock(wraps=db_session.rollback)
    monkeypatch.setattr(db_session, "rollback", rollback)

    with TestClient(test_app) as local_client:
        create_record(local_client, headers, "2026-07-20")
        duplicate = local_client.post(
            BASE_PATH,
            headers=headers,
            json={"record_date": "2026-07-20"},
        )
        recovered = local_client.post(
            BASE_PATH,
            headers=headers,
            json={"record_date": "2026-07-19"},
        )

    assert duplicate.status_code == 409
    assert rollback.call_count == 1
    assert recovered.status_code == 201


def test_commit_failure_rolls_back_without_partial_write(
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(test_app) as setup_client:
        headers, _ = authenticated_user(setup_client)

    original_commit = Session.commit

    def fail_commit(session: Session) -> None:
        raise OperationalError(
            "COMMIT",
            {},
            sqlite3.OperationalError("simulated commit failure"),
        )

    monkeypatch.setattr(Session, "commit", fail_commit)
    with TestClient(test_app, raise_server_exceptions=False) as failing_client:
        response = failing_client.post(
            BASE_PATH,
            headers=headers,
            json={"record_date": "2026-07-20"},
        )
    monkeypatch.setattr(Session, "commit", original_commit)

    with TestClient(test_app) as verification_client:
        missing = verification_client.get(
            f"{BASE_PATH}/2026-07-20",
            headers=headers,
        )

    assert response.status_code == 500
    assert missing.status_code == 404


def test_openapi_declares_authenticated_daily_record_contract(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    collection = schema["paths"][BASE_PATH]
    item = schema["paths"][f"{BASE_PATH}/{{record_date}}"]

    assert set(collection) >= {"get", "post"}
    assert set(item) >= {"get"}
    assert "201" in collection["post"]["responses"]
    assert collection["post"]["security"]
    assert collection["get"]["security"]
    request_schema = schema["components"]["schemas"]["DailyRecordCreate"]
    assert "user_id" not in request_schema["properties"]
    response_schema = collection["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["type"] == "array"
