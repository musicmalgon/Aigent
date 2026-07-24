import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Base
from app.main import create_app


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "jwt_secret_key": "local-only-secret-with-at-least-32-characters",
        "sqladmin_enabled": False,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_app_factory_does_not_create_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("create_all must not run during app startup")

    monkeypatch.setattr(Base.metadata, "create_all", fail_if_called)

    create_app(make_settings())


def test_default_app_has_no_admin_route() -> None:
    application = create_app(make_settings())

    assert all(
        getattr(route, "path", None) != "/admin"
        for route in application.routes
    )


def test_development_can_explicitly_enable_admin() -> None:
    application = create_app(
        make_settings(
            app_env="development",
            sqladmin_enabled=True,
            sqladmin_path="/internal-admin",
        )
    )

    assert any(
        getattr(route, "path", None) == "/internal-admin"
        for route in application.routes
    )


def test_health_and_existing_routes_are_available() -> None:
    application = create_app(make_settings())
    route_paths = {
        path
        for route in application.routes
        if isinstance(path := getattr(route, "path", None), str)
    }

    assert {"/auth/signup", "/auth/login", "/users/me"} <= route_paths

    with TestClient(application) as client:
        assert client.get("/").json() == {"status": "ok"}
        assert client.get("/health").json() == {
            "status": "ok",
            "database": "not_checked",
        }
