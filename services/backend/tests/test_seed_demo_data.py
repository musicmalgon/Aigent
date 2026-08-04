from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.consent import ConsentRecord, ConsentStatus, ConsentType
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    PersistenceBaselineStatus,
    RecoveryReport,
)
from app.models.user import User
from app.scripts.seed_demo_data import (
    HIGH_RISK_EMAIL,
    INSUFFICIENT_EMAIL,
    INSUFFICIENT_RECORD_DAYS,
    NORMAL_EMAIL,
    seed_high_risk_user,
    seed_insufficient_records_user,
    seed_normal_pattern_user,
)
from app.services.baselines import MINIMUM_SAMPLE_DAYS

GENERATION_STATUSES = {"llm_generated", "template_fallback"}


@pytest.fixture
def offline_ai_settings(app_settings: Settings) -> Settings:
    """AI 서비스가 확실히 닿지 않는 포트를 가리켜 폴백 경로를 결정적으로 만든다."""

    return app_settings.model_copy(
        update={"ai_service_base_url": "http://127.0.0.1:9"}
    )


def _user(session: Session, email: str) -> User:
    user = session.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


def _count(session: Session, model: Any, user_id: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.user_id == user_id)
        )
        or 0
    )


def _granted_consent_types(session: Session, user_id: str) -> set[Any]:
    # ConsentRecord는 레거시 Column 스타일이라 consent_type의 정적 타입이
    # Column이다. api/consents.py와 같은 이유로 원소 타입을 Any로 둔다.
    return {
        record.consent_type
        for record in session.scalars(
            select(ConsentRecord).where(
                ConsentRecord.user_id == user_id,
                ConsentRecord.status == ConsentStatus.GRANTED,
            )
        )
    }


def test_insufficient_records_user_has_no_derived_output(
    db_session: Session,
) -> None:
    assert seed_insufficient_records_user(db_session) is True

    user = _user(db_session, INSUFFICIENT_EMAIL)
    assert INSUFFICIENT_RECORD_DAYS < MINIMUM_SAMPLE_DAYS
    assert (
        _count(db_session, BehavioralDailyRecord, user.id)
        == INSUFFICIENT_RECORD_DAYS
    )
    assert _count(db_session, BehavioralBaseline, user.id) == 0
    assert _count(db_session, BurnoutRiskEvaluation, user.id) == 0
    assert _count(db_session, RecoveryReport, user.id) == 0
    assert _granted_consent_types(db_session, user.id) == {
        ConsentType.HEALTH_DATA
    }


def test_normal_pattern_user_has_ready_baseline_only(
    db_session: Session,
) -> None:
    assert seed_normal_pattern_user(db_session) is True

    user = _user(db_session, NORMAL_EMAIL)
    baseline = db_session.scalar(
        select(BehavioralBaseline).where(BehavioralBaseline.user_id == user.id)
    )
    assert baseline is not None
    assert baseline.status is PersistenceBaselineStatus.READY
    assert baseline.sample_days >= MINIMUM_SAMPLE_DAYS
    assert baseline.sleep_minutes is not None
    assert _count(db_session, BurnoutRiskEvaluation, user.id) == 0
    assert _count(db_session, RecoveryReport, user.id) == 0
    assert _granted_consent_types(db_session, user.id) == {
        ConsentType.HEALTH_DATA
    }


def test_high_risk_user_has_elevated_risk_and_recovery_report(
    db_session: Session,
    offline_ai_settings: Settings,
) -> None:
    assert (
        asyncio.run(seed_high_risk_user(db_session, offline_ai_settings))
        is True
    )

    user = _user(db_session, HIGH_RISK_EMAIL)
    baseline = db_session.scalar(
        select(BehavioralBaseline).where(BehavioralBaseline.user_id == user.id)
    )
    assert baseline is not None
    assert baseline.status is PersistenceBaselineStatus.READY
    assert baseline.sample_days >= MINIMUM_SAMPLE_DAYS

    evaluation = db_session.scalar(
        select(BurnoutRiskEvaluation).where(
            BurnoutRiskEvaluation.user_id == user.id
        )
    )
    assert evaluation is not None
    # baseline 윈도우는 악화 구간 앞에서 끊기므로 평소 기준은 건강한 시기다.
    assert baseline.window_end < evaluation.record_date  # type: ignore[operator]
    assert evaluation.level in {"high", "very_high"}
    assert evaluation.score >= 50.0
    assert evaluation.baseline_id == baseline.id

    report = db_session.scalar(
        select(RecoveryReport).where(RecoveryReport.user_id == user.id)
    )
    assert report is not None
    assert report.risk_evaluation_id == evaluation.id
    assert report.generation_status in GENERATION_STATUSES

    assert _granted_consent_types(db_session, user.id) == {
        ConsentType.HEALTH_DATA,
        ConsentType.EMOTION_DIARY,
    }


def test_seeding_every_scenario_is_idempotent(
    db_session: Session,
    offline_ai_settings: Settings,
) -> None:
    assert seed_insufficient_records_user(db_session) is True
    assert seed_normal_pattern_user(db_session) is True
    assert (
        asyncio.run(seed_high_risk_user(db_session, offline_ai_settings))
        is True
    )

    before = {
        model: db_session.scalar(select(func.count()).select_from(model))
        for model in (
            User,
            BehavioralDailyRecord,
            BehavioralBaseline,
            BurnoutRiskEvaluation,
            RecoveryReport,
            ConsentRecord,
        )
    }

    assert seed_insufficient_records_user(db_session) is False
    assert seed_normal_pattern_user(db_session) is False
    assert (
        asyncio.run(seed_high_risk_user(db_session, offline_ai_settings))
        is False
    )

    after = {
        model: db_session.scalar(select(func.count()).select_from(model))
        for model in before
    }
    assert after == before
