from __future__ import annotations

import io
from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect

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


def test_persistence_migration_schema(database_url: str) -> None:
    command.upgrade(make_alembic_config(database_url), "head")
    engine = create_database_engine(database_url)
    try:
        inspector = inspect(engine)
        assert EXPECTED_TABLES <= set(inspector.get_table_names())

        daily_columns = {
            item["name"]
            for item in inspector.get_columns("behavioral_daily_records")
        }
        assert {
            "user_id",
            "record_date",
            "sleep_minutes",
            "subjective_stress",
            "created_at",
            "updated_at",
        } <= daily_columns
        emotion_columns = {
            item["name"]
            for item in inspector.get_columns("emotion_analysis_results")
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
        risk_foreign_keys = inspector.get_foreign_keys(
            "burnout_risk_evaluations"
        )
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
            "ix_behavioral_baselines_user_window_end",
            "ix_risk_evaluations_user_evaluated_at",
            "ix_risk_evaluations_user_record_date",
        } <= index_names
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
    assert str(
        Path("20260725_0002_add_behavioral_persistence")
    ) not in rendered
