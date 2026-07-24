from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import Settings
from app.core.database import Base, create_database_engine
from app.main import create_app

from .conftest import TEST_JWT_SECRET


def development_settings(
    *,
    database_url: str,
    sqladmin_enabled: bool = False,
    sqladmin_path: str = "/admin",
) -> Settings:
    return Settings.model_validate(
        {
            "app_env": "development",
            "database_url": database_url,
            "jwt_secret_key": TEST_JWT_SECRET,
            "jwt_algorithm": "HS256",
            "access_token_expire_minutes": 30,
            "sqladmin_enabled": sqladmin_enabled,
            "sqladmin_path": sqladmin_path,
        }
    )


def route_methods(application: FastAPI) -> set[tuple[str, str]]:
    return {
        (path, method)
        for route in application.routes
        if isinstance(path := getattr(route, "path", None), str)
        for method in getattr(route, "methods", set())
    }


def test_app_factory_and_root_endpoint(
    database_url: str,
) -> None:
    application = create_app(development_settings(database_url=database_url))

    with TestClient(application) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_existing_route_list_is_preserved(database_url: str) -> None:
    application = create_app(development_settings(database_url=database_url))
    routes = route_methods(application)

    assert {
        ("/", "GET"),
        ("/auth/signup", "POST"),
        ("/auth/login", "POST"),
        ("/users/me", "GET"),
        ("/users/me/type", "PATCH"),
    }.issubset(routes)


def test_sqladmin_is_disabled_by_default(database_url: str) -> None:
    application = create_app(development_settings(database_url=database_url))

    assert all(
        not getattr(route, "path", "").startswith("/admin")
        for route in application.routes
    )


def test_sqladmin_can_be_explicitly_enabled_in_development(
    database_url: str,
) -> None:
    settings = development_settings(
        database_url=database_url,
        sqladmin_enabled=True,
        sqladmin_path="/internal-admin",
    )
    admin_engine = create_database_engine(database_url)
    try:
        application = create_app(settings, admin_engine=admin_engine)
        assert any(
            getattr(route, "path", "").startswith("/internal-admin")
            for route in application.routes
        )
    finally:
        admin_engine.dispose()


def test_app_factory_never_calls_create_all(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_create_all(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(Base.metadata, "create_all", fail_create_all)
    create_app(development_settings(database_url=database_url))

    assert called is False
    assert "create_all" not in inspect.getsource(main_module)
