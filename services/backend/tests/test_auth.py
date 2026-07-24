from __future__ import annotations

import uuid
from typing import cast

from fastapi.testclient import TestClient

from app.core.security import create_access_token

EMAIL = "user@example.com"
PASSWORD = "correct-horse-battery-staple"


def signup(client: TestClient, email: str = EMAIL) -> dict[str, object]:
    response = client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def login(
    client: TestClient,
    *,
    email: str = EMAIL,
    password: str = PASSWORD,
) -> str:
    response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return cast(str, response.json()["access_token"])


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_signup_success(client: TestClient) -> None:
    body = signup(client)

    assert body["email"] == EMAIL
    assert body["user_type"] is None
    uuid.UUID(str(body["id"]))
    assert "hashed_password" not in body


def test_duplicate_signup_returns_conflict(client: TestClient) -> None:
    signup(client)

    response = client.post(
        "/auth/signup",
        json={"email": EMAIL, "password": PASSWORD},
    )

    assert response.status_code == 409


def test_login_success(client: TestClient) -> None:
    signup(client)

    response = client.post(
        "/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_rejects_wrong_password(client: TestClient) -> None:
    signup(client)

    response = client.post(
        "/auth/login",
        json={"email": EMAIL, "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_login_rejects_unknown_user(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "missing@example.com", "password": PASSWORD},
    )

    assert response.status_code == 401


def test_users_me_success(client: TestClient) -> None:
    created = signup(client)
    token = login(client)

    response = client.get("/users/me", headers=authorization(token))

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_users_me_rejects_missing_token(client: TestClient) -> None:
    response = client.get("/users/me")

    assert response.status_code == 401


def test_users_me_rejects_invalid_token(client: TestClient) -> None:
    response = client.get(
        "/users/me",
        headers=authorization("not-a-valid-token"),
    )

    assert response.status_code == 401


def test_users_me_rejects_token_for_unknown_user(client: TestClient) -> None:
    token = create_access_token(subject=str(uuid.uuid4()))

    response = client.get("/users/me", headers=authorization(token))

    assert response.status_code == 401


def test_user_type_patch_success(client: TestClient) -> None:
    signup(client)
    token = login(client)

    response = client.patch(
        "/users/me/type",
        headers=authorization(token),
        json={"user_type": "job_seeker"},
    )

    assert response.status_code == 200
    assert response.json()["user_type"] == "job_seeker"


def test_user_type_patch_rejects_unknown_value(client: TestClient) -> None:
    signup(client)
    token = login(client)

    response = client.patch(
        "/users/me/type",
        headers=authorization(token),
        json={"user_type": "unknown"},
    )

    assert response.status_code == 422
