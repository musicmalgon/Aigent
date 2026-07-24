from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command

TEST_JWT_SECRET = "test-only-secret-key-with-at-least-32-characters"
BACKEND_ROOT = Path(__file__).resolve().parents[1]

# The application has validated module-level settings. Tests provide explicit,
# non-production values before importing any app module.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", TEST_JWT_SECRET)
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("SQLADMIN_ENABLED", "false")
os.environ.setdefault("SQLADMIN_PATH", "/admin")

from app.core.config import Settings  # noqa: E402
from app.core.database import (  # noqa: E402
    create_database_engine,
    get_db,
)
from app.main import create_app  # noqa: E402


def make_alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'backend-test.db').as_posix()}"


@pytest.fixture
def migrated_engine(database_url: str) -> Generator[Engine, None, None]:
    command.upgrade(make_alembic_config(database_url), "head")
    engine = create_database_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def app_settings(database_url: str) -> Settings:
    return Settings.model_validate(
        {
            "app_env": "test",
            "database_url": database_url,
            "jwt_secret_key": TEST_JWT_SECRET,
            "jwt_algorithm": "HS256",
            "access_token_expire_minutes": 30,
            "sqladmin_enabled": False,
            "sqladmin_path": "/admin",
        }
    )


@pytest.fixture
def test_app(
    app_settings: Settings,
    migrated_engine: Engine,
) -> Generator[FastAPI, None, None]:
    session_factory = sessionmaker(
        bind=migrated_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    application = create_app(app_settings)

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


@pytest.fixture
def client(test_app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(test_app) as test_client:
        yield test_client
