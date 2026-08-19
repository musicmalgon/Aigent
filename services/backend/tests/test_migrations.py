from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from alembic import command
from app.core.database import Base, create_database_engine
from app.models.user import UserType

from .conftest import make_alembic_config

EXPECTED_USER_COLUMNS = {
    "id",
    "email",
    "hashed_password",
    "name",
    "user_type",
    "created_at",
    "google_sub",
    "google_access_token",
    "google_refresh_token",
    "google_token_expiry",
}
EXPECTED_USER_TYPE_NAMES = {
    "UNIVERSITY_STUDENT",
    "JOB_SEEKER",
    "EARLY_CAREER_WORKER",
}


def test_upgrade_head_creates_expected_users_table(database_url: str) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {"users", "alembic_version"}.issubset(
            set(inspector.get_table_names())
        )
        columns = {
            column["name"] for column in inspector.get_columns("users")
        }
        assert columns == EXPECTED_USER_COLUMNS
        indexes = inspector.get_indexes("users")
        email_index = next(
            index for index in indexes if index["name"] == "ix_users_email"
        )
        assert email_index["unique"] == 1
    finally:
        engine.dispose()


def test_migration_downgrade_and_reupgrade(database_url: str) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = create_database_engine(database_url)
    try:
        assert "users" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        assert "users" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_migration_enum_names_match_model_members() -> None:
    assert set(UserType.__members__) == EXPECTED_USER_TYPE_NAMES
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260725_0001_create_users_table.py"
    ).read_text(encoding="utf-8")

    for name in EXPECTED_USER_TYPE_NAMES:
        assert f'"{name}"' in migration


def test_users_metadata_matches_migration_core_columns() -> None:
    users = Base.metadata.tables["users"]

    assert set(users.columns.keys()) == EXPECTED_USER_COLUMNS
    assert users.c.email.unique is True
    assert users.c.email.index is True
