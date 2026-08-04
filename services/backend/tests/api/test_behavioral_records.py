from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime
from typing import Any, cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.api import behavioral_records as api_module
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models.consent import ConsentRecord, ConsentStatus, ConsentType
from app.models.persistence import BehavioralDailyRecord
from app.models.user import User
from app.repositories import behavioral_records as repository_module
from tests.daily_record_contract import (
    DAILY_RECORD_SCHEMA,
    canonical_daily_record_payload,
    validate_daily_record_response,
)

BASE_PATH = "/api/v1/behavioral-records"
CONSENTS_PATH = "/api/v1/consents"
PASSWORD = "correct-horse-battery-staple1!"


def authenticated_user_without_consent(
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


def grant_health_data_consent(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        CONSENTS_PATH,
        headers=headers,
        json={"consent_type": "health_data", "source": "test_setup"},
    )
    assert response.status_code == 201, response.text


def withdraw_health_data_consent(client: TestClient, headers: dict[str, str]) -> None:
    response = client.delete(f"{CONSENTS_PATH}/health_data", headers=headers)
    assert response.status_code == 201, response.text


def authenticated_user(
    client: TestClient,
    *,
    email: str = "daily-record@example.com",
) -> tuple[dict[str, str], dict[str, object]]:
    # 쓰기 엔드포인트가 health_data 동의를 요구하므로 이 헬퍼는 동의까지 마친
    # 사용자를 돌려준다. 미동의 상태가 필요한 테스트는 위 _without_consent를 쓴다.
    headers, user = authenticated_user_without_consent(client, email=email)
    grant_health_data_consent(client, headers)
    return headers, user


def create_record(
    client: TestClient,
    headers: dict[str, str],
    record_date: str,
    **fields: object,
) -> dict[str, object]:
    response = client.post(
        BASE_PATH,
        headers=headers,
        json=canonical_daily_record_payload(
            record_date=record_date,
            **fields,
        ),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


@pytest.fixture
def legacy_metadata_client(
    test_app: FastAPI,
    db_session: Session,
) -> Generator[tuple[TestClient, dict[str, str]], None, None]:
    user = User(
        email="legacy-daily-record@example.com",
        hashed_password=hash_password(PASSWORD),
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        BehavioralDailyRecord(
            user_id=user.id,
            record_date=date(2026, 7, 20),
            source_by_field=None,
            coverage_by_field=None,
        )
    )
    db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    test_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(test_app) as local_client:
            yield local_client, headers
    finally:
        test_app.dependency_overrides.pop(get_db, None)


def test_create_requires_authentication(client: TestClient) -> None:
    response = client.post(
        BASE_PATH,
        json=canonical_daily_record_payload(),
    )

    assert response.status_code == 401


def test_create_full_record_and_serialize_response(client: TestClient) -> None:
    headers, user = authenticated_user(client)

    body = create_record(
        client,
        headers,
        "2026-07-20",
        sleep_minutes=420,
        bedtime="23:40:00",
        wake_time="06:40:00",
        steps=7420,
        active_minutes=52,
        work_or_study_minutes=480,
        rest_minutes=60,
        exercise_minutes=30,
        schedule_count=5,
        subjective_fatigue=6.0,
        time_zone="Asia/Seoul",
    )

    assert body["user_id"] == user["id"]
    assert body["date"] == "2026-07-20"
    assert body["work_or_study_minutes"] == 480
    assert body["time_zone"] == "Asia/Seoul"
    assert set(body) == set(DAILY_RECORD_SCHEMA["properties"])
    validate_daily_record_response(body)


def test_create_preserves_explicit_nulls(client: TestClient) -> None:
    headers, _ = authenticated_user(client)
    nullable_fields = (
        "sleep_minutes",
        "bedtime",
        "wake_time",
        "steps",
        "active_minutes",
        "exercise_minutes",
        "work_or_study_minutes",
        "rest_minutes",
        "schedule_count",
        "subjective_fatigue",
    )

    explicit_nulls = create_record(
        client,
        headers,
        "2026-07-19",
        **{field: None for field in nullable_fields},
        source_by_field={field: "not_provided" for field in nullable_fields},
        coverage_by_field={field: "unavailable" for field in nullable_fields},
    )

    assert all(explicit_nulls[field] is None for field in nullable_fields)
    validate_daily_record_response(explicit_nulls)


def test_client_cannot_set_user_id_or_unknown_fields(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    for extra in ({"user_id": str(uuid.uuid4())}, {"unexpected": "value"}):
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={**canonical_daily_record_payload(), **extra},
        )
        assert response.status_code == 422

    assert (
        client.get(
            f"{BASE_PATH}/2026-07-20",
            headers=headers,
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "legacy_field",
    [
        "record_date",
        "timezone",
        "study_work_minutes",
        "source",
        "data_completeness",
        "subjective_stress",
    ],
)
def test_legacy_persistence_fields_are_not_public_input(
    client: TestClient,
    legacy_field: str,
) -> None:
    headers, _ = authenticated_user(client)
    response = client.post(
        BASE_PATH,
        headers=headers,
        json={
            **canonical_daily_record_payload(),
            legacy_field: "legacy-value",
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs", "expected_location"),
    [
        (
            "POST",
            BASE_PATH,
            {
                "json": canonical_daily_record_payload(
                    record_date="private-invalid-date"
                )
            },
            "body",
        ),
        (
            "GET",
            BASE_PATH,
            {
                "params": {
                    "date_from": "private-invalid-date",
                    "date_to": "2026-07-20",
                }
            },
            "query",
        ),
        (
            "GET",
            f"{BASE_PATH}/private-invalid-date",
            {},
            "path",
        ),
    ],
)
def test_framework_validation_errors_keep_safe_contract(
    client: TestClient,
    method: str,
    path: str,
    request_kwargs: dict[str, Any],
    expected_location: str,
) -> None:
    headers, _ = authenticated_user(client)

    response = client.request(
        method,
        path,
        headers=headers,
        **request_kwargs,
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail
    assert any(error["loc"][0] == expected_location for error in detail)
    for error in detail:
        assert set(error) == {"type", "loc", "msg"}
        assert isinstance(error["type"], str)
        assert isinstance(error["loc"], list)
        assert isinstance(error["msg"], str)
    assert "private-invalid-date" not in response.text


def test_duplicate_user_date_returns_conflict_and_recovers(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client)
    create_record(client, headers, "2026-07-20")

    duplicate = client.post(
        BASE_PATH,
        headers=headers,
        json=canonical_daily_record_payload(),
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
    assert first["user_id"] != second["user_id"]


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
    validate_daily_record_response(response.json())


def test_read_missing_and_invalid_dates(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    assert (
        client.get(
            f"{BASE_PATH}/2026-07-20",
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"{BASE_PATH}/not-a-date",
            headers=headers,
        ).status_code
        == 422
    )


def test_read_legacy_record_without_field_metadata_returns_service_unavailable(
    legacy_metadata_client: tuple[TestClient, dict[str, str]],
) -> None:
    client, headers = legacy_metadata_client

    response = client.get(f"{BASE_PATH}/2026-07-20", headers=headers)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Behavioral record field metadata is unavailable."
    }


def test_list_with_legacy_record_without_field_metadata_returns_service_unavailable(
    legacy_metadata_client: tuple[TestClient, dict[str, str]],
) -> None:
    client, headers = legacy_metadata_client

    response = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_from": "2026-07-20", "date_to": "2026-07-20"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Behavioral record field metadata is unavailable."
    }


def test_records_are_isolated_between_users(client: TestClient) -> None:
    owner_headers, _ = authenticated_user(client, email="owner@example.com")
    other_headers, _ = authenticated_user(client, email="other@example.com")
    create_record(client, owner_headers, "2026-07-20")

    assert (
        client.get(
            f"{BASE_PATH}/2026-07-20",
            headers=other_headers,
        ).status_code
        == 404
    )
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
    items = response.json()
    assert [item["date"] for item in items] == [
        "2026-07-03",
        "2026-07-02",
        "2026-07-01",
    ]
    for item in items:
        validate_daily_record_response(item)


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
    assert [item["date"] for item in response.json()] == [
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
        steps=0,
        active_minutes=1440,
        work_or_study_minutes=1440,
        rest_minutes=0,
        exercise_minutes=1440,
        schedule_count=0,
        subjective_fatigue=10.1,
    )

    assert body["sleep_minutes"] == 0
    assert body["steps"] == 0
    assert body["active_minutes"] == 1440
    assert body["work_or_study_minutes"] == 1440
    assert body["subjective_fatigue"] == 10.1
    validate_daily_record_response(body)


@pytest.mark.parametrize(
    "arbitrary_precision_value",
    [
        0,
        2_147_483_647,
        2_147_483_648,
        9_223_372_036_854_775_807,
        9_223_372_036_854_775_808,
        2**100 + 12345,
    ],
)
def test_arbitrary_precision_integers_round_trip(
    client: TestClient,
    arbitrary_precision_value: int,
) -> None:
    headers, _ = authenticated_user(client)

    created = create_record(
        client,
        headers,
        "2026-07-20",
        steps=arbitrary_precision_value,
        schedule_count=arbitrary_precision_value,
    )
    fetched = client.get(
        f"{BASE_PATH}/2026-07-20",
        headers=headers,
    )

    assert created["steps"] == arbitrary_precision_value
    assert created["schedule_count"] == arbitrary_precision_value
    assert fetched.status_code == 200
    assert fetched.json()["steps"] == arbitrary_precision_value
    assert fetched.json()["schedule_count"] == arbitrary_precision_value
    validate_daily_record_response(fetched.json())


@pytest.mark.parametrize(
    ("value", "metadata_field", "metadata_value"),
    [
        (None, "coverage_by_field", "complete"),
        (420, "coverage_by_field", "unavailable"),
        (420, "source_by_field", "not_provided"),
    ],
)
def test_post_rejects_cross_field_metadata_mismatches(
    client: TestClient,
    value: int | None,
    metadata_field: str,
    metadata_value: str,
) -> None:
    headers, _ = authenticated_user(client)
    payload = canonical_daily_record_payload(sleep_minutes=value)
    payload[metadata_field]["sleep_minutes"] = metadata_value

    response = client.post(BASE_PATH, headers=headers, json=payload)

    assert response.status_code == 422
    assert (
        client.get(f"{BASE_PATH}/2026-07-20", headers=headers).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sleep_minutes", -1),
        ("sleep_minutes", 1441),
        ("steps", -1),
        ("steps", 1.5),
        ("active_minutes", 1441),
        ("work_or_study_minutes", 1441),
        ("rest_minutes", -1),
        ("exercise_minutes", 1441),
        ("schedule_count", -1),
        ("schedule_count", 1.5),
        ("subjective_fatigue", -0.1),
        ("time_zone", "not/a/real-zone"),
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
        json={
            **canonical_daily_record_payload(),
            field: value,
        },
    )

    assert response.status_code == 422
    assert (
        client.get(
            f"{BASE_PATH}/2026-07-20",
            headers=headers,
        ).status_code
        == 404
    )


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
        json=canonical_daily_record_payload(
            record_date="2026-07-20",
            time_zone="Asia/Seoul",
        ),
    )
    rejected = client.post(
        BASE_PATH,
        headers=headers,
        json=canonical_daily_record_payload(
            record_date="2026-07-21",
            time_zone="America/New_York",
        ),
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
        json=canonical_daily_record_payload(),
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
    db_session.flush()
    # 이 테스트는 rollback 호출 횟수를 세므로 동의도 HTTP가 아니라 DB에 직접 심는다.
    db_session.add(
        ConsentRecord(
            user_id=user.id,
            consent_type=ConsentType.HEALTH_DATA,
            status=ConsentStatus.GRANTED,
            granted_at=datetime.now(UTC),
            withdrawn_at=None,
            source="test_setup",
        )
    )
    db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}

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
            json=canonical_daily_record_payload(),
        )
        recovered = local_client.post(
            BASE_PATH,
            headers=headers,
            json=canonical_daily_record_payload(record_date="2026-07-19"),
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
            json=canonical_daily_record_payload(),
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
    shared_properties = set(DAILY_RECORD_SCHEMA["properties"])
    assert set(request_schema["properties"]) == shared_properties - {"user_id"}
    assert set(request_schema["required"]) == shared_properties - {"user_id"}
    for component_name in ("DailyRecordCreate", "DailyRecordRead"):
        assert (
            schema["components"]["schemas"][component_name]["allOf"]
            == DAILY_RECORD_SCHEMA["allOf"]
        )
    response_schema = collection["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["type"] == "array"


def test_create_without_consent_is_forbidden(client: TestClient) -> None:
    headers, _ = authenticated_user_without_consent(
        client,
        email="no-consent-create@example.com",
    )

    response = client.post(
        BASE_PATH,
        headers=headers,
        json=canonical_daily_record_payload(),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "health_data 동의가 필요합니다"}


def test_create_after_consent_withdrawn_is_forbidden(client: TestClient) -> None:
    headers, _ = authenticated_user(client, email="withdrawn-create@example.com")
    withdraw_health_data_consent(client, headers)

    response = client.post(
        BASE_PATH,
        headers=headers,
        json=canonical_daily_record_payload(),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "health_data 동의가 필요합니다"}


def test_update_without_consent_is_forbidden(client: TestClient) -> None:
    headers, _ = authenticated_user(client, email="withdrawn-update@example.com")
    create_record(client, headers, "2026-07-20")
    withdraw_health_data_consent(client, headers)

    response = client.put(
        f"{BASE_PATH}/2026-07-20",
        headers=headers,
        json=canonical_daily_record_payload(record_date="2026-07-20", steps=1234),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "health_data 동의가 필요합니다"}


def test_read_and_delete_work_without_consent(client: TestClient) -> None:
    # 동의 철회 후에도 본인 데이터 조회/삭제는 열려 있어야 한다 — 삭제까지 막히면
    # 동의를 철회한 사용자가 자기 데이터를 지울 방법이 사라진다.
    headers, _ = authenticated_user(client, email="read-delete-no-consent@example.com")
    create_record(client, headers, "2026-07-20")
    withdraw_health_data_consent(client, headers)

    listed = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_from": "2026-07-20", "date_to": "2026-07-20"},
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1

    by_date = client.get(f"{BASE_PATH}/2026-07-20", headers=headers)
    assert by_date.status_code == 200, by_date.text

    deleted = client.delete(f"{BASE_PATH}/2026-07-20", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"{BASE_PATH}/2026-07-20", headers=headers).status_code == 404
