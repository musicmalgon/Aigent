from fastapi.testclient import TestClient


def authenticated_headers(client: TestClient) -> dict[str, str]:
    credentials = {
        "email": "person@example.com",
        "password": "correct-horse-battery-staple",
    }
    assert client.post("/auth/signup", json=credentials).status_code == 201
    response = client.post("/auth/login", json=credentials)
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_current_user_requires_authentication(client: TestClient) -> None:
    response = client.get("/users/me")

    assert response.status_code in {401, 403}


def test_current_user_and_user_type_update(client: TestClient) -> None:
    headers = authenticated_headers(client)

    current_response = client.get("/users/me", headers=headers)
    assert current_response.status_code == 200
    assert current_response.json()["user_type"] is None

    update_response = client.patch(
        "/users/me/type",
        headers=headers,
        json={"user_type": "job_seeker"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["user_type"] == "job_seeker"


def test_user_type_rejects_unknown_value(client: TestClient) -> None:
    response = client.patch(
        "/users/me/type",
        headers=authenticated_headers(client),
        json={"user_type": "not-a-real-user-type"},
    )

    assert response.status_code == 422
