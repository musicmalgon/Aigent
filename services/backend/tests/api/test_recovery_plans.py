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
