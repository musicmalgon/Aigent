from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppEnvironment, Settings

from .conftest import BACKEND_ROOT, TEST_JWT_SECRET


def settings_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "app_env": "development",
        "database_url": "sqlite:///./development.db",
        "jwt_secret_key": TEST_JWT_SECRET,
        "jwt_algorithm": "HS256",
        "access_token_expire_minutes": 30,
        "sqladmin_enabled": False,
        "sqladmin_path": "/admin",
    }
    payload.update(overrides)
    return payload


def test_development_settings_load() -> None:
    settings = Settings.model_validate(settings_payload())

    assert settings.app_env is AppEnvironment.DEVELOPMENT
    assert settings.database_url.endswith("development.db")


def test_test_settings_use_separate_database() -> None:
    development = Settings.model_validate(settings_payload())
    test = Settings.model_validate(
        settings_payload(
            app_env="test",
            database_url="sqlite:///./test.db",
        )
    )

    assert test.app_env is AppEnvironment.TEST
    assert test.database_url != development.database_url


def test_production_requires_jwt_secret() -> None:
    payload = settings_payload(app_env="production")
    payload.pop("jwt_secret_key")

    with pytest.raises(ValidationError):
        Settings.model_validate(payload)


def test_app_import_fails_clearly_without_jwt_secret() -> None:
    environment = os.environ.copy()
    environment.pop("JWT_SECRET_KEY", None)

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "jwt_secret_key" in result.stderr


@pytest.mark.parametrize(
    "weak_secret",
    [
        "secret" * 8,
        "changeme" * 5,
        "your-secret-key-" * 3,
        "development-secret-" * 2,
        "default" * 6,
        "replace-with-a-long-random-secret",
    ],
)
def test_production_rejects_public_or_weak_secrets(
    weak_secret: str,
) -> None:
    with pytest.raises(ValidationError, match="public placeholder"):
        Settings.model_validate(
            settings_payload(
                app_env="production",
                jwt_secret_key=weak_secret,
            )
        )


def test_production_accepts_explicit_strong_secret() -> None:
    settings = Settings.model_validate(
        settings_payload(
            app_env="production",
            jwt_secret_key="x4J!9qL2#vN7@rT5$kP8^mC3&zW6*eH1",
        )
    )

    assert settings.app_env is AppEnvironment.PRODUCTION


@pytest.mark.parametrize("app_env", ["test", "production"])
def test_sqladmin_is_rejected_outside_development(app_env: str) -> None:
    with pytest.raises(ValidationError, match="only be enabled in development"):
        Settings.model_validate(
            settings_payload(
                app_env=app_env,
                sqladmin_enabled=True,
            )
        )


def test_invalid_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(settings_payload(app_env="staging"))


@pytest.mark.parametrize("minutes", [0, -1, 10081])
def test_invalid_token_expiration_is_rejected(minutes: int) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            settings_payload(access_token_expire_minutes=minutes)
        )


@pytest.mark.parametrize("path", ["/", "admin", "/docs", "/redoc"])
def test_invalid_sqladmin_path_is_rejected(path: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(settings_payload(sqladmin_path=path))


def test_database_url_for_logging_hides_password() -> None:
    settings = Settings.model_validate(
        settings_payload(
            database_url="postgresql+psycopg://user:sensitive@db/aigent"
        )
    )

    rendered = settings.database_url_for_logging
    assert "sensitive" not in rendered
    assert "***" in rendered


def test_env_example_contains_no_real_secret() -> None:
    env_path = BACKEND_ROOT / ".env.example"
    contents = env_path.read_text(encoding="utf-8")
    secret_line = next(
        line for line in contents.splitlines() if line.startswith("JWT_SECRET_KEY=")
    )

    assert "replace-with" in secret_line
    assert TEST_JWT_SECRET not in contents
    assert not (BACKEND_ROOT / ".env").is_file()


def test_env_example_path_is_inside_backend() -> None:
    assert (BACKEND_ROOT / ".env.example").is_relative_to(Path.cwd())
