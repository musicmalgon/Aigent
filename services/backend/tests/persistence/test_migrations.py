from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import String, inspect, text

from alembic import command
from app.core.database import Base, create_database_engine

from ..conftest import BACKEND_ROOT, make_alembic_config

EXPECTED_TABLES = {
    "users",
    "behavioral_daily_records",
    "emotion_analysis_results",
    "behavioral_baselines",
    "burnout_risk_evaluations",
    "alembic_version",
}


def test_migration_logging_preserves_existing_loggers(database_url: str) -> None:
    logger = logging.getLogger("app.clients.ai")
    original_disabled = logger.disabled
    logger.disabled = False
    try:
        command.upgrade(make_alembic_config(database_url), "head")
        assert logger.disabled is False
    finally:
        logger.disabled = original_disabled


def test_persistence_migration_schema(database_url: str) -> None:
    command.upgrade(make_alembic_config(database_url), "head")
    engine = create_database_engine(database_url)
    try:
        inspector = inspect(engine)
        assert EXPECTED_TABLES <= set(inspector.get_table_names())

        daily_column_info = {
            item["name"]: item
            for item in inspector.get_columns("behavioral_daily_records")
        }
        daily_columns = set(daily_column_info)
        assert {
            "user_id",
            "record_date",
            "sleep_minutes",
            "bedtime",
            "wake_time",
            "steps",
            "active_minutes",
            "source_by_field",
            "coverage_by_field",
            "subjective_stress",
            "subjective_fatigue",
            "created_at",
            "updated_at",
        } <= daily_columns
        assert isinstance(daily_column_info["steps"]["type"], String)
        assert isinstance(daily_column_info["schedule_count"]["type"], String)
        daily_checks = {
            item["name"]: " ".join(item["sqltext"].split())
            for item in inspector.get_check_constraints("behavioral_daily_records")
        }
        assert "CAST(steps AS NUMERIC) >= 0" in daily_checks["ck_daily_steps"]
        assert (
            "CAST(schedule_count AS NUMERIC) >= 0"
            in daily_checks["ck_daily_schedule_count"]
        )
        assert (
            "active_minutes >= 0 AND active_minutes <= 1440"
            in daily_checks["ck_daily_active_minutes"]
        )
        fatigue_check = daily_checks["ck_daily_subjective_fatigue"]
        assert "subjective_fatigue >= 0" in fatigue_check
        assert "subjective_fatigue <= 10" not in fatigue_check
        baseline_checks = {
            item["name"]: " ".join(item["sqltext"].split())
            for item in inspector.get_check_constraints("behavioral_baselines")
        }
        baseline_fatigue_check = baseline_checks[
            "ck_baseline_subjective_fatigue"
        ]
        assert "subjective_fatigue >= 0" in baseline_fatigue_check
        assert "subjective_fatigue <= 10" not in baseline_fatigue_check
        emotion_columns = {
            item["name"] for item in inspector.get_columns("emotion_analysis_results")
        }
        assert emotion_columns == {
            "id",
            "user_id",
            "record_date",
            "analyzed_at",
            "model_version",
            "predicted_emotion",
            "confidence",
            "is_uncertain",
            "probabilities",
            "input_hash",
            "created_at",
        }
        unique_constraints = inspector.get_unique_constraints(
            "behavioral_daily_records"
        )
        assert any(
            item["column_names"] == ["user_id", "record_date"]
            for item in unique_constraints
        )
        risk_foreign_keys = inspector.get_foreign_keys("burnout_risk_evaluations")
        assert {item["referred_table"] for item in risk_foreign_keys} == {
            "users",
            "behavioral_daily_records",
            "emotion_analysis_results",
            "behavioral_baselines",
        }
        index_names = {
            item["name"]
            for table in (
                "emotion_analysis_results",
                "behavioral_baselines",
                "burnout_risk_evaluations",
            )
            for item in inspector.get_indexes(table)
        }
        assert {
            "ix_emotion_results_user_analyzed_at",
            "ix_emotion_results_user_record_date_analyzed_at",
            "ix_behavioral_baselines_user_window_end",
            "ix_behavioral_baselines_user_status_window_end",
            "ix_risk_evaluations_user_evaluated_at",
            "ix_risk_evaluations_user_record_date",
        } <= index_names
    finally:
        engine.dispose()


def test_upgrade_preserves_null_metadata_for_existing_daily_records(
    database_url: str,
) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "20260725_0002")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password) "
                    "VALUES (:id, :email, :hashed_password)"
                ),
                {
                    "id": "legacy-user",
                    "email": "legacy@example.com",
                    "hashed_password": "legacy-password-hash",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO behavioral_daily_records "
                    "(id, user_id, record_date) "
                    "VALUES (:id, :user_id, :record_date)"
                ),
                {
                    "id": "legacy-record",
                    "user_id": "legacy-user",
                    "record_date": "2026-07-20",
                },
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT source_by_field, coverage_by_field "
                        "FROM behavioral_daily_records "
                        "WHERE id = :id"
                    ),
                    {"id": "legacy-record"},
                )
                .mappings()
                .one()
            )
        assert row["source_by_field"] is None
        assert row["coverage_by_field"] is None
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("subjective_fatigue", "schedule_count"),
    [
        (10.1, None),
        (None, str(2**31)),
    ],
)
def test_downgrade_preflight_rejects_values_not_representable_by_0002(
    database_url: str,
    subjective_fatigue: float | None,
    schedule_count: str | None,
) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password) "
                    "VALUES (:id, :email, :hashed_password)"
                ),
                {
                    "id": "downgrade-user",
                    "email": "downgrade@example.com",
                    "hashed_password": "downgrade-password-hash",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO behavioral_daily_records "
                    "(id, user_id, record_date, "
                    "subjective_fatigue, schedule_count) "
                    "VALUES (:id, :user_id, :record_date, "
                    ":subjective_fatigue, :schedule_count)"
                ),
                {
                    "id": "downgrade-record",
                    "user_id": "downgrade-user",
                    "record_date": "2026-07-20",
                    "subjective_fatigue": subjective_fatigue,
                    "schedule_count": schedule_count,
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        command.downgrade(config, "20260725_0002")

    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            row = (
                connection.execute(
                    text(
                        "SELECT subjective_fatigue, schedule_count "
                        "FROM behavioral_daily_records "
                        "WHERE id = :id"
                    ),
                    {"id": "downgrade-record"},
                )
                .mappings()
                .one()
            )

        assert revision == "20260727_0003"
        assert row["subjective_fatigue"] == subjective_fatigue
        assert row["schedule_count"] == schedule_count
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("column_name", "value"),
    [
        ("bedtime", "23:30:00"),
        ("wake_time", "06:30:00"),
        ("steps", "7420"),
        ("active_minutes", 52),
        ("source_by_field", "{}"),
        ("coverage_by_field", "{}"),
    ],
)
def test_downgrade_preflight_rejects_any_0003_only_field_data(
    database_url: str,
    column_name: str,
    value: object,
) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password) "
                    "VALUES (:id, :email, :hashed_password)"
                ),
                {
                    "id": "lossy-downgrade-user",
                    "email": "lossy-downgrade@example.com",
                    "hashed_password": "downgrade-password-hash",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO behavioral_daily_records "
                    f"(id, user_id, record_date, {column_name}) "
                    "VALUES (:id, :user_id, :record_date, :value)"
                ),
                {
                    "id": "lossy-downgrade-record",
                    "user_id": "lossy-downgrade-user",
                    "record_date": "2026-07-20",
                    "value": value,
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="0003-only field data"):
        command.downgrade(config, "20260725_0002")

    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260727_0003"
            )
            assert connection.scalar(
                text(
                    "SELECT COUNT(*) FROM behavioral_daily_records "
                    "WHERE id = :id"
                ),
                {"id": "lossy-downgrade-record"},
            ) == 1
    finally:
        engine.dispose()


def test_downgrade_previous_revision_and_reupgrade(
    database_url: str,
) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "20260725_0001")
    engine = create_database_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "users" in tables
        assert "behavioral_daily_records" not in tables
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_baseline_fatigue_above_ten_is_preserved_at_head(
    database_url: str,
) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password) "
                    "VALUES (:id, :email, :hashed_password)"
                ),
                {
                    "id": "baseline-fatigue-user",
                    "email": "baseline-fatigue@example.com",
                    "hashed_password": "baseline-fatigue-password-hash",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO behavioral_baselines "
                    "(id, user_id, window_start, window_end, sample_days, "
                    "subjective_fatigue, status, algorithm_version) "
                    "VALUES (:id, :user_id, :window_start, :window_end, "
                    ":sample_days, :subjective_fatigue, :status, "
                    ":algorithm_version)"
                ),
                {
                    "id": "baseline-fatigue",
                    "user_id": "baseline-fatigue-user",
                    "window_start": "2026-07-01",
                    "window_end": "2026-07-14",
                    "sample_days": 14,
                    "subjective_fatigue": 12.5,
                    "status": "ready",
                    "algorithm_version": "behavioral-baseline-mean-v1",
                },
            )

        with engine.connect() as connection:
            value = connection.scalar(
                text(
                    "SELECT subjective_fatigue "
                    "FROM behavioral_baselines "
                    "WHERE id = :id"
                ),
                {"id": "baseline-fatigue"},
            )

        assert value == 12.5
    finally:
        engine.dispose()


def test_0004_downgrade_preflight_rejects_baseline_fatigue_above_ten(
    database_url: str,
) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password) "
                    "VALUES (:id, :email, :hashed_password)"
                ),
                {
                    "id": "downgrade-baseline-user",
                    "email": "downgrade-baseline@example.com",
                    "hashed_password": "downgrade-baseline-password-hash",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO behavioral_baselines "
                    "(id, user_id, window_start, window_end, sample_days, "
                    "subjective_fatigue, status, algorithm_version) "
                    "VALUES (:id, :user_id, :window_start, :window_end, "
                    ":sample_days, :subjective_fatigue, :status, "
                    ":algorithm_version)"
                ),
                {
                    "id": "downgrade-baseline",
                    "user_id": "downgrade-baseline-user",
                    "window_start": "2026-07-01",
                    "window_end": "2026-07-14",
                    "sample_days": 14,
                    "subjective_fatigue": 12.5,
                    "status": "ready",
                    "algorithm_version": "behavioral-baseline-mean-v1",
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="behavioral_baselines"):
        command.downgrade(config, "20260727_0003")

    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260729_0005"
            )
            assert connection.scalar(
                text(
                    "SELECT subjective_fatigue "
                    "FROM behavioral_baselines "
                    "WHERE id = :id"
                ),
                {"id": "downgrade-baseline"},
            ) == 12.5
    finally:
        engine.dispose()


def test_0004_downgrade_preserves_compatible_baseline_fatigue(
    database_url: str,
) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password) "
                    "VALUES (:id, :email, :hashed_password)"
                ),
                {
                    "id": "compatible-downgrade-user",
                    "email": "compatible-downgrade@example.com",
                    "hashed_password": "compatible-downgrade-password-hash",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO behavioral_baselines "
                    "(id, user_id, window_start, window_end, sample_days, "
                    "subjective_fatigue, status, algorithm_version) "
                    "VALUES (:id, :user_id, :window_start, :window_end, "
                    ":sample_days, :subjective_fatigue, :status, "
                    ":algorithm_version)"
                ),
                {
                    "id": "compatible-downgrade-baseline",
                    "user_id": "compatible-downgrade-user",
                    "window_start": "2026-07-01",
                    "window_end": "2026-07-14",
                    "sample_days": 14,
                    "subjective_fatigue": 10,
                    "status": "ready",
                    "algorithm_version": "behavioral-baseline-mean-v1",
                },
            )
    finally:
        engine.dispose()

    command.downgrade(config, "20260727_0003")

    engine = create_database_engine(database_url)
    try:
        inspector = inspect(engine)
        index_names = {
            item["name"]
            for item in inspector.get_indexes("behavioral_baselines")
        }
        fatigue_check = next(
            item["sqltext"]
            for item in inspector.get_check_constraints(
                "behavioral_baselines"
            )
            if item["name"] == "ck_baseline_subjective_fatigue"
        )
        with engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            fatigue = connection.scalar(
                text(
                    "SELECT subjective_fatigue "
                    "FROM behavioral_baselines "
                    "WHERE id = :id"
                ),
                {"id": "compatible-downgrade-baseline"},
            )

        assert revision == "20260727_0003"
        assert fatigue == 10
        assert (
            "ix_behavioral_baselines_user_status_window_end"
            not in index_names
        )
        assert "subjective_fatigue <= 10" in " ".join(fatigue_check.split())
    finally:
        engine.dispose()


def test_model_metadata_has_persistence_tables() -> None:
    assert EXPECTED_TABLES - {"alembic_version"} <= set(Base.metadata.tables)


def test_head_has_no_model_metadata_drift(database_url: str) -> None:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")

    command.check(config)


def test_postgresql_offline_sql_can_be_rendered() -> None:
    output = io.StringIO()
    config = Config(
        str(BACKEND_ROOT / "alembic.ini"),
        output_buffer=output,
    )
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://user:password@localhost/aigent",
    )

    command.upgrade(config, "head", sql=True)

    rendered = output.getvalue()
    assert "CREATE TABLE behavioral_daily_records" in rendered
    assert "CREATE TABLE burnout_risk_evaluations" in rendered
    assert "ON DELETE SET NULL" in rendered
    assert "ON DELETE CASCADE" in rendered
    assert "ix_emotion_results_user_record_date_analyzed_at" in rendered
    assert "ix_behavioral_baselines_user_status_window_end" in rendered
    assert str(Path("20260725_0002_add_behavioral_persistence")) not in rendered


def test_postgresql_offline_downgrade_sql_can_be_rendered() -> None:
    output = io.StringIO()
    config = Config(
        str(BACKEND_ROOT / "alembic.ini"),
        output_buffer=output,
    )
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://user:password@localhost/aigent",
    )

    command.downgrade(
        config,
        "20260727_0004:20260727_0003",
        sql=True,
    )

    rendered = output.getvalue()
    assert "DROP INDEX ix_behavioral_baselines_user_status_window_end" in rendered
    assert "DROP INDEX ix_emotion_results_user_record_date_analyzed_at" in rendered
    assert "ALTER TABLE behavioral_baselines" in rendered


def test_previous_postgresql_offline_downgrade_sql_can_be_rendered() -> None:
    output = io.StringIO()
    config = Config(
        str(BACKEND_ROOT / "alembic.ini"),
        output_buffer=output,
    )
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://user:password@localhost/aigent",
    )

    command.downgrade(
        config,
        "20260727_0003:20260725_0002",
        sql=True,
    )

    rendered = output.getvalue()
    assert "ALTER TABLE behavioral_daily_records" in rendered
    assert "schedule_count::integer" in rendered
