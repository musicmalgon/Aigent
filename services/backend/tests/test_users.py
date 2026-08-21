from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.user import User


def authenticated_headers(client: TestClient) -> dict[str, str]:
    credentials = {
        "email": "person@example.com",
        "password": "correct-horse-battery-staple1!",
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


def test_password_update_on_google_only_account_returns_clear_error(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    """구글 전용 계정(hashed_password=None)엔 애초에 비밀번호가 없다. 예전엔
    verify_password(plain, None)을 그대로 호출해 passlib이 TypeError를
    던지며 500으로 깨졌고, 프론트는 JSON 파싱 실패로 "요청 실패: 500"만
    보여줬다(#H5). 이젠 바꿀 비밀번호 자체가 없다는 걸 400으로 명확히
    알려줘야 한다."""

    with Session(migrated_engine) as session:
        user = User(
            email="google-only-password@example.com",
            hashed_password=None,
            google_sub="sub-google-only-password",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    headers = {"Authorization": f"Bearer {create_access_token(subject=user_id)}"}

    response = client.patch(
        "/users/me/password",
        headers=headers,
        json={"current_password": "아무거나", "new_password": "new-Password1!"},
    )

    assert response.status_code == 400, response.text
    assert "구글" in response.json()["detail"]
