from __future__ import annotations

from typing import cast

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.clients.ai import AIServiceClient
from app.core.config import Settings
from app.main import create_app


def make_settings() -> Settings:
    return Settings.model_validate(
        {
            "app_env": "test",
            "database_url": "sqlite:///:memory:",
            "jwt_secret_key": "test-only-secret-with-at-least-32-characters",
            "sqladmin_enabled": False,
        }
    )


class LifecycleClient:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


def test_app_owned_client_is_created_lazily_reused_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[LifecycleClient] = []

    def create_client(settings: Settings) -> AIServiceClient:
        del settings
        client = LifecycleClient()
        created.append(client)
        return cast(AIServiceClient, client)

    monkeypatch.setattr(main_module, "create_ai_service_client", create_client)
    application = create_app(make_settings())

    assert created == []
    with TestClient(application) as client:
        assert len(created) == 1
        assert application.state.ai_service_client is created[0]
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 200
        assert len(created) == 1

    assert created[0].close_calls == 1


def test_injected_client_remains_owned_by_caller() -> None:
    injected = LifecycleClient()
    application = create_app(
        make_settings(),
        ai_service_client=cast(AIServiceClient, injected),
    )

    with TestClient(application) as client:
        assert application.state.ai_service_client is injected
        assert client.get("/").status_code == 200

    assert injected.close_calls == 0


def test_emotion_analysis_route_coexists_with_existing_routes() -> None:
    application = create_app(make_settings())
    route_paths = {
        path
        for route in application.routes
        if isinstance(path := getattr(route, "path", None), str)
    }

    assert {
        "/auth/signup",
        "/auth/login",
        "/users/me",
        "/api/v1/behavioral-records",
        "/api/v1/emotion-analyses",
    } <= route_paths
