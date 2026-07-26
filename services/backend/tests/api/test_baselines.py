from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api import baselines as api_module
from app.models.persistence import (
    BehavioralBaseline,
    EmotionAnalysisResult,
    PersistenceBaselineStatus,
)
from app.repositories.behavioral_records import create_daily_record
from app.repositories.emotion_results import create_emotion_result
from app.schemas.persistence import (
    DailyRecordCreate,
    EmotionLabel,
    EmotionResultCreate,
)
from app.services import baselines as service_module
from app.services.baselines import BASELINE_ALGORITHM_VERSION

BASE_PATH = "/api/v1/baselines"
PASSWORD = "correct-horse-battery-staple"
TODAY = date(2026, 7, 27)


@pytest.fixture(autouse=True)
def fixed_utc_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_module, "_utc_today", lambda: TODAY)


def authenticated_user(
    client: TestClient,
    *,
    email: str = "baseline-api@example.com",
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


def seed_daily_records(
    engine: Engine,
    *,
    user_id: str,
    records: list[dict[str, object]],
) -> None:
    with Session(engine) as session:
        for values in records:
            create_daily_record(
                session,
                user_id=user_id,
                payload=DailyRecordCreate.model_validate(values),
            )
        session.commit()


def emotion_probabilities(
    *,
    joy: float,
) -> dict[EmotionLabel, float]:
    remaining = round((1.0 - joy) / 5.0, 10)
    values = {
        EmotionLabel.JOY: joy,
        EmotionLabel.ANXIETY: remaining,
        EmotionLabel.EMBARRASSMENT: remaining,
        EmotionLabel.ANGER: remaining,
        EmotionLabel.SADNESS: remaining,
        EmotionLabel.HURT: remaining,
    }
    values[EmotionLabel.HURT] += 1.0 - sum(values.values())
    return values


def seed_emotion_result(
    engine: Engine,
    *,
    user_id: str,
    record_date: date | None,
    joy: float,
    analyzed_at: datetime,
) -> None:
    probabilities = emotion_probabilities(joy=joy)
    predicted_emotion = max(probabilities, key=probabilities.__getitem__)
    with Session(engine) as session:
        create_emotion_result(
            session,
            user_id=user_id,
            payload=EmotionResultCreate(
                record_date=record_date,
                analyzed_at=analyzed_at,
                model_version="coarse-emotion-test-v1",
                predicted_emotion=predicted_emotion,
                confidence=max(probabilities.values()),
                is_uncertain=False,
                probabilities=probabilities,
                input_hash=None,
            ),
        )
        session.commit()


def seed_baselines(
    engine: Engine,
    *,
    user_id: str,
    rows: list[dict[str, Any]],
) -> list[str]:
    ids: list[str] = []
    with Session(engine) as session:
        for values in rows:
            window_end = cast(date, values["window_end"])
            baseline_id = cast(str, values.get("id", str(uuid.uuid4())))
            baseline = BehavioralBaseline(
                id=baseline_id,
                user_id=user_id,
                window_start=cast(
                    date,
                    values.get(
                        "window_start",
                        window_end - timedelta(days=13),
                    ),
                ),
                window_end=window_end,
                sample_days=cast(int, values.get("sample_days", 7)),
                status=cast(
                    PersistenceBaselineStatus,
                    values.get(
                        "status",
                        PersistenceBaselineStatus.READY,
                    ),
                ),
                algorithm_version=cast(
                    str,
                    values.get(
                        "algorithm_version",
                        BASELINE_ALGORITHM_VERSION,
                    ),
                ),
                created_at=cast(datetime, values["created_at"]),
            )
            session.add(baseline)
            ids.append(baseline_id)
        session.commit()
    return ids


def baseline_count(engine: Engine, *, user_id: str | None = None) -> int:
    with Session(engine) as session:
        statement = select(func.count()).select_from(BehavioralBaseline)
        if user_id is not None:
            statement = statement.where(BehavioralBaseline.user_id == user_id)
        return session.scalar(statement) or 0


def test_all_endpoints_require_authentication(client: TestClient) -> None:
    responses = [
        client.post(BASE_PATH, json={"as_of_date": "2026-07-20"}),
        client.get(f"{BASE_PATH}/latest-ready"),
        client.get(BASE_PATH),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]


def test_default_window_creates_ready_baseline_and_safe_log(
    client: TestClient,
    migrated_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, user_id = authenticated_user(client)
    seed_daily_records(
        migrated_engine,
        user_id=user_id,
        records=[
            {
                "record_date": date(2026, 7, 14) + timedelta(days=offset),
                "sleep_minutes": 400 + offset,
            }
            for offset in range(7)
        ],
    )

    with caplog.at_level(logging.INFO, logger="app.api.baselines"):
        response = client.post(
            BASE_PATH,
            headers=headers,
            json={"as_of_date": "2026-07-20"},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    uuid.UUID(body["id"])
    uuid.UUID(body["user_id"])
    assert body["user_id"] == user_id
    assert body["window_start"] == "2026-07-07"
    assert body["window_end"] == "2026-07-20"
    assert body["sample_days"] == 7
    assert body["sleep_minutes"] == 403
    assert body["status"] == "ready"
    assert body["algorithm_version"] == BASELINE_ALGORITHM_VERSION
    created_at = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
    assert created_at.utcoffset() is not None
    assert baseline_count(migrated_engine, user_id=user_id) == 1
    assert "Baseline created" in caplog.text
    assert "sample_days=7" in caplog.text
    assert user_id not in caplog.text


@pytest.mark.parametrize(
    ("window_days", "expected_start"),
    [
        (14, "2026-07-14"),
        (28, "2026-06-30"),
    ],
)
def test_explicit_window_boundaries_are_inclusive(
    client: TestClient,
    window_days: int,
    expected_start: str,
) -> None:
    headers, _ = authenticated_user(client)

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={
            "as_of_date": "2026-07-27",
            "window_days": window_days,
        },
    )

    assert response.status_code == 201
    assert response.json()["window_start"] == expected_start
    assert response.json()["window_end"] == "2026-07-27"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"as_of_date": "2026-07-20", "window_days": 13},
        {"as_of_date": "2026-07-20", "window_days": 29},
        {"as_of_date": "2026-07-20", "user_id": "private-user-id"},
        {"as_of_date": "2026-07-20", "status": "ready"},
        {"as_of_date": "2026-07-20", "sample_days": 7},
        {
            "as_of_date": "2026-07-20",
            "algorithm_version": "private-version",
        },
        {"as_of_date": "2026-07-20", "unknown": "private-value"},
    ],
)
def test_invalid_or_server_owned_create_fields_are_rejected_without_write(
    client: TestClient,
    migrated_engine: Engine,
    payload: dict[str, object],
) -> None:
    headers, user_id = authenticated_user(client)

    response = client.post(BASE_PATH, headers=headers, json=payload)

    assert response.status_code == 422
    assert baseline_count(migrated_engine, user_id=user_id) == 0
    for error in response.json()["detail"]:
        assert set(error) == {"type", "loc", "msg"}
    assert "private-user-id" not in response.text
    assert "private-version" not in response.text
    assert "private-value" not in response.text


def test_future_as_of_date_is_rejected_without_write(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-28"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "as_of_date cannot be in the future."
    }
    assert baseline_count(migrated_engine, user_id=user_id) == 0


def test_exactly_six_days_creates_insufficient_row_with_201(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    seed_daily_records(
        migrated_engine,
        user_id=user_id,
        records=[
            {
                "record_date": date(2026, 7, 15) + timedelta(days=offset),
                "sleep_minutes": 420,
            }
            for offset in range(6)
        ],
    )

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-20"},
    )

    assert response.status_code == 201
    assert response.json()["sample_days"] == 6
    assert response.json()["status"] == "insufficient"
    assert baseline_count(migrated_engine, user_id=user_id) == 1


def test_repeated_period_creation_is_append_only(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    request = {"as_of_date": "2026-07-20", "window_days": 14}

    first = client.post(BASE_PATH, headers=headers, json=request)
    second = client.post(BASE_PATH, headers=headers, json=request)
    history = client.get(
        BASE_PATH,
        headers=headers,
        params={"limit": 100},
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["window_start"] == second.json()["window_start"]
    assert first.json()["window_end"] == second.json()["window_end"]
    assert baseline_count(migrated_engine, user_id=user_id) == 2
    assert {item["id"] for item in history.json()} == {
        first.json()["id"],
        second.json()["id"],
    }
    assert next(
        item for item in history.json() if item["id"] == first.json()["id"]
    ) == first.json()


def test_aggregation_scope_bounds_latest_emotion_nulls_zero_and_rounding(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    _, other_user_id = authenticated_user(
        client,
        email="other-baseline@example.com",
    )
    seed_daily_records(
        migrated_engine,
        user_id=user_id,
        records=[
            {
                "record_date": date(2026, 7, 7),
                "sleep_minutes": 0,
                "subjective_stress": 1.11111,
            },
            {
                "record_date": date(2026, 7, 8),
                "sleep_minutes": 2,
                "subjective_stress": 2.22222,
            },
            {"record_date": date(2026, 7, 9)},
            {
                "record_date": date(2026, 7, 10),
                "rest_minutes": 3,
            },
            {
                "record_date": date(2026, 7, 6),
                "sleep_minutes": 1000,
            },
            {
                "record_date": date(2026, 7, 21),
                "sleep_minutes": 1000,
            },
        ],
    )
    seed_daily_records(
        migrated_engine,
        user_id=other_user_id,
        records=[
            {
                "record_date": date(2026, 7, 12),
                "sleep_minutes": 1000,
            }
        ],
    )
    seed_emotion_result(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 10),
        joy=0.8,
        analyzed_at=datetime(2026, 7, 10, 8, tzinfo=UTC),
    )
    seed_emotion_result(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 10),
        joy=0.1,
        analyzed_at=datetime(2026, 7, 10, 9, tzinfo=UTC),
    )
    seed_emotion_result(
        migrated_engine,
        user_id=user_id,
        record_date=None,
        joy=0.0,
        analyzed_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
    )
    seed_emotion_result(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 21),
        joy=0.0,
        analyzed_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
    )
    seed_emotion_result(
        migrated_engine,
        user_id=other_user_id,
        record_date=date(2026, 7, 12),
        joy=0.0,
        analyzed_at=datetime(2026, 7, 12, 9, tzinfo=UTC),
    )

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-20"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["sample_days"] == 3
    assert body["sleep_minutes"] == 1
    assert body["subjective_stress"] == 1.6667
    assert body["rest_minutes"] == 3
    assert body["negative_emotion_probability"] == 0.9
    assert body["status"] == "insufficient"


def test_all_null_daily_record_produces_null_averages_and_zero_samples(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    seed_daily_records(
        migrated_engine,
        user_id=user_id,
        records=[{"record_date": date(2026, 7, 20)}],
    )

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-20"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["sample_days"] == 0
    assert body["status"] == "insufficient"
    for field in (
        "sleep_minutes",
        "study_work_minutes",
        "rest_minutes",
        "exercise_minutes",
        "schedule_count",
        "subjective_stress",
        "subjective_fatigue",
        "negative_emotion_probability",
    ):
        assert body[field] is None


def test_invalid_stored_emotion_data_returns_safe_500_without_baseline(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    with Session(migrated_engine) as session:
        session.add(
            EmotionAnalysisResult(
                user_id=user_id,
                record_date=date(2026, 7, 20),
                analyzed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
                model_version="invalid-test-model",
                predicted_emotion=EmotionLabel.JOY.value,
                confidence=1.0,
                is_uncertain=False,
                probabilities={EmotionLabel.JOY.value: 1.0},
                input_hash=None,
            )
        )
        session.commit()

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-20"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Baseline operation failed."}
    assert "invalid-test-model" not in response.text
    assert baseline_count(migrated_engine, user_id=user_id) == 0


def test_latest_ready_ignores_newer_insufficient_and_other_user(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    other_headers, other_user_id = authenticated_user(
        client,
        email="other-ready@example.com",
    )
    seed_daily_records(
        migrated_engine,
        user_id=user_id,
        records=[
            {
                "record_date": date(2026, 7, 1) + timedelta(days=offset),
                "sleep_minutes": 420,
            }
            for offset in range(7)
        ],
    )
    ready = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-07"},
    )
    insufficient = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-27"},
    )
    seed_daily_records(
        migrated_engine,
        user_id=other_user_id,
        records=[
            {
                "record_date": date(2026, 7, 21) + timedelta(days=offset),
                "sleep_minutes": 420,
            }
            for offset in range(7)
        ],
    )
    other_ready = client.post(
        BASE_PATH,
        headers=other_headers,
        json={"as_of_date": "2026-07-27"},
    )

    response = client.get(f"{BASE_PATH}/latest-ready", headers=headers)

    assert ready.json()["status"] == "ready"
    assert insufficient.json()["status"] == "insufficient"
    assert other_ready.json()["status"] == "ready"
    assert response.status_code == 200
    assert response.json() == ready.json()


def test_latest_ready_returns_404_when_only_insufficient_exists(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client)
    created = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-20"},
    )

    response = client.get(f"{BASE_PATH}/latest-ready", headers=headers)

    assert created.status_code == 201
    assert created.json()["status"] == "insufficient"
    assert response.status_code == 404
    assert response.json() == {"detail": "Ready baseline not found."}


def test_latest_ready_prefers_creation_time_then_stable_id(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    earlier = datetime(2026, 7, 20, 11, tzinfo=UTC)
    latest = datetime(2026, 7, 20, 12, tzinfo=UTC)
    lower_id = "00000000-0000-0000-0000-000000000001"
    higher_id = "00000000-0000-0000-0000-000000000002"
    seed_baselines(
        migrated_engine,
        user_id=user_id,
        rows=[
            {
                "id": "00000000-0000-0000-0000-000000000003",
                "window_end": date(2026, 7, 20),
                "created_at": earlier,
            },
            {
                "id": lower_id,
                "window_end": date(2026, 7, 10),
                "created_at": latest,
            },
            {
                "id": higher_id,
                "window_end": date(2026, 7, 9),
                "created_at": latest,
            },
        ],
    )

    response = client.get(f"{BASE_PATH}/latest-ready", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == higher_id


def test_history_includes_both_statuses_duplicates_and_is_user_scoped(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    _, other_user_id = authenticated_user(
        client,
        email="other-history@example.com",
    )
    timestamps = [
        datetime(2026, 7, 20, hour, tzinfo=UTC)
        for hour in (8, 9, 10)
    ]
    ids = seed_baselines(
        migrated_engine,
        user_id=user_id,
        rows=[
            {
                "window_end": date(2026, 7, 20),
                "status": PersistenceBaselineStatus.INSUFFICIENT,
                "sample_days": 6,
                "created_at": timestamps[0],
            },
            {
                "window_end": date(2026, 7, 20),
                "status": PersistenceBaselineStatus.READY,
                "created_at": timestamps[1],
            },
            {
                "window_end": date(2026, 7, 19),
                "status": PersistenceBaselineStatus.READY,
                "created_at": timestamps[2],
            },
        ],
    )
    seed_baselines(
        migrated_engine,
        user_id=other_user_id,
        rows=[
            {
                "window_end": date(2026, 7, 21),
                "created_at": datetime(2026, 7, 20, 11, tzinfo=UTC),
            }
        ],
    )

    response = client.get(BASE_PATH, headers=headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [
        ids[2],
        ids[1],
        ids[0],
    ]
    assert {item["status"] for item in response.json()} == {
        "ready",
        "insufficient",
    }
    assert [item["window_end"] for item in response.json()].count(
        "2026-07-20"
    ) == 2


def test_history_status_and_period_end_filters_are_inclusive(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    created_at = datetime(2026, 7, 20, 12, tzinfo=UTC)
    ids = seed_baselines(
        migrated_engine,
        user_id=user_id,
        rows=[
            {
                "window_end": date(2026, 7, 9),
                "created_at": created_at,
            },
            {
                "window_end": date(2026, 7, 10),
                "created_at": created_at + timedelta(minutes=1),
            },
            {
                "window_end": date(2026, 7, 15),
                "status": PersistenceBaselineStatus.INSUFFICIENT,
                "sample_days": 6,
                "created_at": created_at + timedelta(minutes=2),
            },
            {
                "window_end": date(2026, 7, 20),
                "created_at": created_at + timedelta(minutes=3),
            },
            {
                "window_end": date(2026, 7, 21),
                "created_at": created_at + timedelta(minutes=4),
            },
        ],
    )

    ready = client.get(
        BASE_PATH,
        headers=headers,
        params={
            "status": "ready",
            "date_from": "2026-07-10",
            "date_to": "2026-07-20",
        },
    )
    insufficient = client.get(
        BASE_PATH,
        headers=headers,
        params={"status": "insufficient"},
    )
    invalid_status = client.get(
        BASE_PATH,
        headers=headers,
        params={"status": "unknown"},
    )
    invalid_range = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_from": "2026-07-20", "date_to": "2026-07-19"},
    )
    from_only = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_from": "2026-07-20"},
    )
    to_only = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_to": "2026-07-10"},
    )

    assert [item["id"] for item in ready.json()] == [ids[3], ids[1]]
    assert [item["id"] for item in insufficient.json()] == [ids[2]]
    assert invalid_status.status_code == 422
    assert invalid_range.status_code == 422
    assert [item["id"] for item in from_only.json()] == [ids[4], ids[3]]
    assert [item["id"] for item in to_only.json()] == [ids[1], ids[0]]


def test_history_id_tie_breaker_stabilizes_offset_pagination(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    created_at = datetime(2026, 7, 20, 12, tzinfo=UTC)
    ids = [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
    ]
    seed_baselines(
        migrated_engine,
        user_id=user_id,
        rows=[
            {
                "id": baseline_id,
                "window_end": date(2026, 7, 20),
                "created_at": created_at,
            }
            for baseline_id in ids
        ],
    )

    pages = [
        client.get(
            BASE_PATH,
            headers=headers,
            params={"limit": 1, "offset": offset},
        ).json()
        for offset in range(3)
    ]

    assert [page[0]["id"] for page in pages] == list(reversed(ids))


def test_history_pagination_defaults_limits_offsets_and_empty_result(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    start = datetime(2026, 7, 1, tzinfo=UTC)
    ids = seed_baselines(
        migrated_engine,
        user_id=user_id,
        rows=[
            {
                "window_end": date(2026, 7, 1) + timedelta(days=index),
                "created_at": start + timedelta(minutes=index),
            }
            for index in range(21)
        ],
    )

    default_page = client.get(BASE_PATH, headers=headers)
    maximum = client.get(
        BASE_PATH,
        headers=headers,
        params={"limit": 100},
    )
    offset = client.get(
        BASE_PATH,
        headers=headers,
        params={"limit": 1, "offset": 20},
    )
    empty = client.get(
        BASE_PATH,
        headers=headers,
        params={"offset": 21},
    )

    assert len(default_page.json()) == 20
    assert default_page.json()[0]["id"] == ids[-1]
    assert len(maximum.json()) == 21
    assert [item["id"] for item in offset.json()] == [ids[0]]
    assert empty.json() == []


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_invalid_pagination_is_rejected_safely(
    client: TestClient,
    params: dict[str, int],
) -> None:
    headers, _ = authenticated_user(client)

    response = client.get(BASE_PATH, headers=headers, params=params)

    assert response.status_code == 422
    for error in response.json()["detail"]:
        assert set(error) == {"type", "loc", "msg"}


def test_commit_failure_rolls_back_without_partial_write(
    client: TestClient,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, user_id = authenticated_user(client)
    original_commit = Session.commit

    def fail_commit(session: Session) -> None:
        raise OperationalError(
            "COMMIT",
            {},
            sqlite3.OperationalError("private commit detail"),
        )

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-20"},
    )
    monkeypatch.setattr(Session, "commit", original_commit)

    assert response.status_code == 500
    assert response.json() == {"detail": "Baseline operation failed."}
    assert "private" not in response.text
    assert baseline_count(migrated_engine, user_id=user_id) == 0


def test_flush_failure_rolls_back_and_hides_database_details(
    client: TestClient,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, user_id = authenticated_user(client)

    def fail_flush(*args: object, **kwargs: object) -> None:
        raise OperationalError(
            "INSERT private_table",
            {},
            sqlite3.OperationalError("private database detail"),
        )

    monkeypatch.setattr(service_module, "create_baseline", fail_flush)
    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"as_of_date": "2026-07-20"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Baseline operation failed."}
    assert "private" not in response.text
    assert baseline_count(migrated_engine, user_id=user_id) == 0


def test_openapi_declares_authenticated_baseline_contract(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    collection = schema["paths"][BASE_PATH]
    latest_ready = schema["paths"][f"{BASE_PATH}/latest-ready"]["get"]
    create = collection["post"]
    history = collection["get"]
    request_schema = schema["components"]["schemas"]["BaselineCreate"]
    response_schema = schema["components"]["schemas"]["BaselineRead"]
    history_parameters = {
        parameter["name"]: parameter for parameter in history["parameters"]
    }

    assert set(collection) >= {"get", "post"}
    assert create["security"]
    assert history["security"]
    assert latest_ready["security"]
    assert "201" in create["responses"]
    assert request_schema["required"] == ["as_of_date"]
    assert request_schema["properties"]["window_days"]["default"] == 14
    assert request_schema["properties"]["window_days"]["minimum"] == 14
    assert request_schema["properties"]["window_days"]["maximum"] == 28
    assert request_schema["additionalProperties"] is False
    assert "user_id" not in request_schema["properties"]
    assert {
        "id",
        "user_id",
        "window_start",
        "window_end",
        "sample_days",
        "status",
        "algorithm_version",
        "created_at",
    }.issubset(response_schema["properties"])
    assert history_parameters["limit"]["schema"]["default"] == 20
    assert history_parameters["limit"]["schema"]["maximum"] == 100
    assert history_parameters["offset"]["schema"]["default"] == 0
    assert "user_id" not in history_parameters
