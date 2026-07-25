from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.risk.models import BaselineStatus
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    EmotionAnalysisResult,
    PersistenceBaselineStatus,
)
from app.models.user import User
from app.repositories import PersistenceScopeError
from app.repositories.risk_evaluations import (
    get_latest_risk_evaluation,
    list_risk_evaluations,
)
from app.services.risk_adapter import build_risk_request
from app.services.risk_evaluation import evaluate_and_store

from .helpers import daily_record, emotion_result


def baseline(
    session: Session,
    *,
    user_id: str,
    window_end: date,
    sample_days: int = 14,
) -> BehavioralBaseline:
    item = BehavioralBaseline(
        user_id=user_id,
        window_start=window_end - timedelta(days=13),
        window_end=window_end,
        sample_days=sample_days,
        sleep_minutes=450,
        study_work_minutes=420,
        rest_minutes=90,
        exercise_minutes=30,
        schedule_count=3,
        subjective_stress=4,
        subjective_fatigue=4,
        negative_emotion_probability=0.4,
        status=(
            PersistenceBaselineStatus.READY
            if sample_days >= 7
            else PersistenceBaselineStatus.INSUFFICIENT
        ),
        algorithm_version="behavioral-baseline-mean-v1",
    )
    session.add(item)
    session.flush()
    return item


def test_adapter_preserves_signals_and_full_emotion_distribution(
    db_session: Session,
    user: User,
) -> None:
    current_date = date(2026, 7, 20)
    daily = daily_record(
        db_session,
        user_id=user.id,
        record_date=current_date,
        sleep_minutes=None,
        study_work_minutes=600,
    )
    emotion = emotion_result(
        db_session,
        user_id=user.id,
        record_date=current_date,
        joy=0.2,
    )
    ready_baseline = baseline(
        db_session,
        user_id=user.id,
        window_end=current_date - timedelta(days=1),
    )

    request = build_risk_request(
        user_id=user.id,
        daily_record=daily,
        emotion_result=emotion,
        baseline=ready_baseline,
    )

    assert request.current.sleep_minutes is None
    assert request.current.work_or_study_minutes == 600
    assert request.current.emotion_confidence == 0.8
    assert request.current.emotion_uncertain is False
    assert request.current.emotion_probabilities is not None
    assert len(request.current.emotion_probabilities.as_tuple()) == 6
    assert request.baseline is not None
    assert request.baseline.sample_days == 14


def test_adapter_handles_insufficient_and_missing_baseline(
    db_session: Session,
    user: User,
) -> None:
    current_date = date(2026, 7, 20)
    daily = daily_record(
        db_session,
        user_id=user.id,
        record_date=current_date,
    )
    insufficient = baseline(
        db_session,
        user_id=user.id,
        window_end=current_date - timedelta(days=1),
        sample_days=6,
    )

    request = build_risk_request(
        user_id=user.id,
        daily_record=daily,
        emotion_result=None,
        baseline=insufficient,
    )
    missing = build_risk_request(
        user_id=user.id,
        daily_record=daily,
        emotion_result=None,
        baseline=None,
    )

    assert request.baseline is not None
    assert request.baseline.sample_days == 6
    assert missing.baseline is None
    assert missing.current.emotion_probabilities is None


def test_evaluate_store_is_append_only_and_preserves_provenance(
    db_session: Session,
    user: User,
) -> None:
    current_date = date(2026, 7, 20)
    daily = daily_record(
        db_session,
        user_id=user.id,
        record_date=current_date,
        sleep_minutes=300,
        subjective_stress=9,
    )
    emotion = emotion_result(
        db_session,
        user_id=user.id,
        record_date=current_date,
        joy=0.1,
    )
    ready_baseline = baseline(
        db_session,
        user_id=user.id,
        window_end=current_date - timedelta(days=1),
    )

    first, first_result = evaluate_and_store(
        db_session,
        user_id=user.id,
        daily_record=daily,
        emotion_result=emotion,
        baseline=ready_baseline,
    )
    second, _ = evaluate_and_store(
        db_session,
        user_id=user.id,
        daily_record=daily,
        emotion_result=emotion,
        baseline=ready_baseline,
    )

    assert first.id != second.id
    assert first.daily_record_id == daily.id
    assert first.emotion_analysis_result_id == emotion.id
    assert first.baseline_id == ready_baseline.id
    assert first.engine_version == "burnout-risk-rules-v1"
    assert first.score == first_result.score
    assert first.category_scores
    assert isinstance(first.factors, list)
    assert first.summary
    assert first_result.baseline_status is BaselineStatus.READY
    assert get_latest_risk_evaluation(db_session, user_id=user.id) is second
    assert len(list_risk_evaluations(db_session, user_id=user.id)) == 2


def test_cross_user_provenance_is_rejected(
    db_session: Session,
    user: User,
    other_user: User,
) -> None:
    daily = daily_record(
        db_session,
        user_id=user.id,
        record_date=date(2026, 7, 20),
    )

    with pytest.raises(PersistenceScopeError):
        build_risk_request(
            user_id=other_user.id,
            daily_record=daily,
            emotion_result=None,
            baseline=None,
        )


def test_deleting_input_sets_provenance_null_but_keeps_evaluation(
    db_session: Session,
    user: User,
) -> None:
    daily = daily_record(
        db_session,
        user_id=user.id,
        record_date=date(2026, 7, 20),
    )
    evaluation, _ = evaluate_and_store(
        db_session,
        user_id=user.id,
        daily_record=daily,
        emotion_result=None,
        baseline=None,
    )
    evaluation_id = evaluation.id

    db_session.delete(daily)
    db_session.flush()
    db_session.expire_all()

    preserved = db_session.get(BurnoutRiskEvaluation, evaluation_id)
    assert preserved is not None
    assert preserved.daily_record_id is None


def test_deleting_user_cascades_all_owned_rows(
    db_session: Session,
    user: User,
) -> None:
    daily = daily_record(
        db_session,
        user_id=user.id,
        record_date=date(2026, 7, 20),
    )
    emotion = emotion_result(
        db_session,
        user_id=user.id,
        record_date=daily.record_date,
    )
    ready_baseline = baseline(
        db_session,
        user_id=user.id,
        window_end=daily.record_date - timedelta(days=1),
    )
    evaluate_and_store(
        db_session,
        user_id=user.id,
        daily_record=daily,
        emotion_result=emotion,
        baseline=ready_baseline,
    )

    db_session.delete(user)
    db_session.flush()

    for model in (
        BehavioralDailyRecord,
        EmotionAnalysisResult,
        BehavioralBaseline,
        BurnoutRiskEvaluation,
    ):
        count = db_session.scalar(select(func.count()).select_from(model))
        assert count == 0
