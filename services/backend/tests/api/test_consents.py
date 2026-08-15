from __future__ import annotations

from typing import cast

from fastapi.testclient import TestClient

BASE_PATH = "/api/v1/consents"
PASSWORD = "correct-horse-battery-staple1!"
SOURCE = "onboarding_consent_screen"


def authenticated_user(
    client: TestClient,
    *,
    email: str = "consent@example.com",
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


def grant(
    client: TestClient,
    headers: dict[str, str],
    consent_type: str,
) -> dict[str, object]:
    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"consent_type": consent_type, "source": SOURCE},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def current_status(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    response = client.get(BASE_PATH, headers=headers)
    assert response.status_code == 200, response.text
    return {item["consent_type"]: item["status"] for item in response.json()}


def test_grant_requires_authentication(client: TestClient) -> None:
    response = client.post(
        BASE_PATH,
        json={"consent_type": "health_data", "source": SOURCE},
    )

    assert response.status_code == 401


def test_grant_health_data_consent(client: TestClient) -> None:
    headers, user = authenticated_user(client)

    body = grant(client, headers, "health_data")

    assert body["user_id"] == user["id"]
    assert body["consent_type"] == "health_data"
    assert body["status"] == "granted"
    assert body["withdrawn_at"] is None
    assert body["source"] == SOURCE
    assert body["granted_at"]


def test_get_returns_granted_consent(client: TestClient) -> None:
    headers, _ = authenticated_user(client)
    created = grant(client, headers, "health_data")

    response = client.get(BASE_PATH, headers=headers)

    assert response.status_code == 200
    assert response.json() == [created]


def test_get_is_empty_without_any_consent(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    response = client.get(BASE_PATH, headers=headers)

    assert response.status_code == 200
    assert response.json() == []


def test_withdraw_appends_record_and_preserves_grant_time(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client)
    granted = grant(client, headers, "health_data")

    response = client.delete(f"{BASE_PATH}/health_data", headers=headers)

    assert response.status_code == 201, response.text
    withdrawn = response.json()
    assert withdrawn["id"] != granted["id"]
    assert withdrawn["status"] == "withdrawn"
    assert withdrawn["withdrawn_at"] is not None
    assert withdrawn["granted_at"] == granted["granted_at"]
    assert withdrawn["source"] == granted["source"]


def test_get_after_withdrawal_shows_latest_record(client: TestClient) -> None:
    headers, _ = authenticated_user(client)
    grant(client, headers, "health_data")
    withdrawn = client.delete(f"{BASE_PATH}/health_data", headers=headers).json()

    response = client.get(BASE_PATH, headers=headers)

    assert response.status_code == 200
    assert response.json() == [withdrawn]


def test_withdraw_without_any_consent_returns_not_found(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client)

    response = client.delete(f"{BASE_PATH}/emotion_diary", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "해당 동의 항목에 대한 활성 동의가 없습니다"


def test_withdrawing_twice_returns_not_found(client: TestClient) -> None:
    headers, _ = authenticated_user(client)
    grant(client, headers, "health_data")

    first = client.delete(f"{BASE_PATH}/health_data", headers=headers)
    second = client.delete(f"{BASE_PATH}/health_data", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 404
    assert current_status(client, headers) == {"health_data": "withdrawn"}


def test_unknown_consent_type_is_rejected(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    assert (
        client.delete(f"{BASE_PATH}/marketing_email", headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            BASE_PATH,
            headers=headers,
            json={"consent_type": "marketing_email", "source": SOURCE},
        ).status_code
        == 422
    )


def test_consent_types_are_independent(client: TestClient) -> None:
    headers, _ = authenticated_user(client)
    grant(client, headers, "health_data")
    grant(client, headers, "emotion_diary")

    withdrawn = client.delete(f"{BASE_PATH}/health_data", headers=headers)

    assert withdrawn.status_code == 201
    assert current_status(client, headers) == {
        "health_data": "withdrawn",
        "emotion_diary": "granted",
    }


def test_regranting_after_withdrawal_restores_granted_status(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client)
    grant(client, headers, "health_data")
    client.delete(f"{BASE_PATH}/health_data", headers=headers)

    regranted = grant(client, headers, "health_data")

    assert current_status(client, headers) == {"health_data": "granted"}
    assert client.get(BASE_PATH, headers=headers).json() == [regranted]


def test_consents_are_isolated_between_users(client: TestClient) -> None:
    owner_headers, owner = authenticated_user(client, email="owner@example.com")
    other_headers, other = authenticated_user(client, email="other@example.com")
    grant(client, owner_headers, "health_data")

    assert client.get(BASE_PATH, headers=other_headers).json() == []
    assert (
        client.delete(f"{BASE_PATH}/health_data", headers=other_headers).status_code
        == 404
    )

    grant(client, other_headers, "emotion_diary")

    owner_items = client.get(BASE_PATH, headers=owner_headers).json()
    other_items = client.get(BASE_PATH, headers=other_headers).json()
    assert [item["consent_type"] for item in owner_items] == ["health_data"]
    assert [item["consent_type"] for item in other_items] == ["emotion_diary"]
    assert owner_items[0]["user_id"] == owner["id"]
    assert other_items[0]["user_id"] == other["id"]
