from __future__ import annotations

from fastapi.testclient import TestClient

BASE_PATH = "/api/v1/recovery-plans"
PASSWORD = "correct-horse-battery-staple1!"


def authenticated_headers(client: TestClient, email: str) -> dict[str, str]:
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
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_recovery_plan_items_are_selectable_and_track_completion(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "recovery-plan@example.com")

    assert client.get(BASE_PATH, headers=headers).json() == []
    created = client.post(
        BASE_PATH,
        headers=headers,
        json={"action_id": "REST_30"},
    )
    assert created.status_code == 201
    item = created.json()
    assert item["status"] == "planned"
    assert item["title"] == "방해받지 않는 휴식 30분"

    duplicate = client.post(
        BASE_PATH,
        headers=headers,
        json={"action_id": "REST_30"},
    )
    assert duplicate.status_code == 409

    completed = client.patch(
        f"{BASE_PATH}/{item['id']}",
        headers=headers,
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None


def test_recovery_plan_rejects_unknown_actions(client: TestClient) -> None:
    headers = authenticated_headers(client, "recovery-plan-invalid@example.com")
    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"action_id": "NOT_A_REAL_ACTION"},
    )
    assert response.status_code == 422


def test_recovery_plan_settings_default_to_null_for_a_fresh_user(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "recovery-plan-settings-fresh@example.com")

    response = client.get(f"{BASE_PATH}/settings", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["notification_time"] is None
    assert body["target_period_start"] is None
    assert body["target_period_end"] is None


def test_recovery_plan_settings_notification_time_persists(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "recovery-plan-settings-time@example.com")

    updated = client.patch(
        f"{BASE_PATH}/settings",
        headers=headers,
        json={"notification_time": "20:00:00"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["notification_time"] == "20:00:00"

    # 새로고침(=다시 조회)해도 유지돼야 한다.
    refetched = client.get(f"{BASE_PATH}/settings", headers=headers)
    assert refetched.json()["notification_time"] == "20:00:00"
    # 목표 기간은 이번 요청에 아예 없었으니 건드리지 않아야(=null 유지) 한다.
    assert refetched.json()["target_period_start"] is None


def test_recovery_plan_settings_target_period_persists_and_round_trips(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "recovery-plan-settings-period@example.com")

    updated = client.patch(
        f"{BASE_PATH}/settings",
        headers=headers,
        json={
            "target_period_start": "2026-08-21",
            "target_period_end": "2026-09-21",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["target_period_start"] == "2026-08-21"
    assert updated.json()["target_period_end"] == "2026-09-21"

    refetched = client.get(f"{BASE_PATH}/settings", headers=headers)
    assert refetched.json()["target_period_start"] == "2026-08-21"
    assert refetched.json()["target_period_end"] == "2026-09-21"
    # 알림시간은 이번 요청에 없었으니 그대로 null이어야 한다.
    assert refetched.json()["notification_time"] is None


def test_recovery_plan_settings_rejects_end_before_start(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "recovery-plan-settings-bad-range@example.com")

    response = client.patch(
        f"{BASE_PATH}/settings",
        headers=headers,
        json={
            "target_period_start": "2026-09-21",
            "target_period_end": "2026-08-21",
        },
    )

    assert response.status_code == 422, response.text


def test_recovery_plan_settings_rejects_partial_period(
    client: TestClient,
) -> None:
    """시작일/종료일은 한 쌍으로만 바꿀 수 있다 -- 하나만 보내면 거부한다."""
    headers = authenticated_headers(client, "recovery-plan-settings-partial@example.com")

    response = client.patch(
        f"{BASE_PATH}/settings",
        headers=headers,
        json={"target_period_start": "2026-08-21"},
    )

    assert response.status_code == 422, response.text


def test_recovery_plan_settings_never_reflects_another_users_data(
    client: TestClient,
) -> None:
    owner = authenticated_headers(client, "recovery-plan-settings-owner@example.com")
    other = authenticated_headers(client, "recovery-plan-settings-other@example.com")

    client.patch(
        f"{BASE_PATH}/settings",
        headers=owner,
        json={"notification_time": "21:30:00"},
    )

    other_settings = client.get(f"{BASE_PATH}/settings", headers=other)
    assert other_settings.json()["notification_time"] is None


def test_recovery_plan_settings_require_authentication(client: TestClient) -> None:
    assert client.get(f"{BASE_PATH}/settings").status_code == 401
    assert client.patch(f"{BASE_PATH}/settings", json={}).status_code == 401
