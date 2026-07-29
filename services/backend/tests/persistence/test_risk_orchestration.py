from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    EmotionAnalysisResult,
    PersistenceBaselineStatus,
)
from app.models.user import User
from app.repositories.baselines import get_baseline
from app.repositories.behavioral_records import get_daily_record
from app.repositories.emotion_results import get_emotion_result
from app.services.risk_evaluation import (
    DailyRecordNotFoundError,
    FutureEvaluationDateError,
    ReadyBaselineNotFoundError,
    RiskInputsChangedError,
    RiskInputUnavailableError,
    evaluate_prepared_risk,
    prepare_risk_evaluation,
    store_prepared_risk_evaluation,
)

from .helpers import daily_record, emotion_result


def ready_baseline(
    session: Session,
    *,
    user_id: str,
    window_end: date,
) -> BehavioralBaseline:
    baseline = BehavioralBaseline(
        user_id=user_id,
        window_start=window_end - timedelta(days=13),
        window_end=window_end,
        sample_days=14,
        sleep_minutes=450,
        study_work_minutes=420,
        rest_minutes=90,
        exercise_minutes=30,
        schedule_count=3,
        subjective_stress=4,
        subjective_fatigue=4,
        negative_emotion_probability=0.4,
        status=PersistenceBaselineStatus.READY,
        algorithm_version="behavioral-baseline-mean-v1",
    )
    session.add(baseline)
    session.flush()
    return baseline


def evaluation_count(session: Session, *, user_id: str) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(BurnoutRiskEvaluation)
        .where(BurnoutRiskEvaluation.user_id == user_id)
    )
    assert count is not None
    return count


def test_prepare_evaluate_store_is_append_only_across_transactions(
    db_session: Session,
    user: User,
) -> None:
    target_date = date(2026, 7, 20)
    daily = daily_record(
        db_session,
        user_id=user.id,
        record_date=target_date,
        subjective_fatigue=12,
    )
    emotion = emotion_result(
        db_session,
        user_id=user.id,
        record_date=target_date,
        joy=0.1,
    )
    baseline = ready_baseline(
        db_session,
        user_id=user.id,
        window_end=target_date - timedelta(days=1),
    )
    db_session.commit()

    created_ids: list[str] = []
    for _ in range(2):
        prepared = prepare_risk_evaluation(
            db_session,
            user_id=user.id,
            record_date=target_date,
            now=datetime(2026, 7, 21, tzinfo=UTC),
        )
        assert prepared.daily_record_id == daily.id
        assert prepared.emotion_analysis_id == emotion.id
        assert prepared.baseline_id == baseline.id
        assert prepared.request.current.subjective_fatigue == 12

        db_session.rollback()
        assert not db_session.in_transaction()
        result = evaluate_prepared_risk(prepared)
        assert not db_session.in_transaction()

        evaluation = store_prepared_risk_evaluation(
            db_session,
            prepared=prepared,
            result=result,
        )
        created_ids.append(evaluation.id)
        db_session.commit()

    assert len(set(created_ids)) == 2
    assert evaluation_count(db_session, user_id=user.id) == 2


def test_prepare_allows_missing_same_date_emotion(
    db_session: Session,
    user: User,
) -> None:
    target_date = date(2026, 7, 20)
    daily_record(
        db_session,
        user_id=user.id,
        record_date=target_date,
    )
    ready_baseline(
        db_session,
        user_id=user.id,
        window_end=target_date - timedelta(days=1),
    )

    prepared = prepare_risk_evaluation(
        db_session,
        user_id=user.id,
        record_date=target_date,
        now=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert prepared.emotion_analysis_id is None
    assert prepared.request.current.emotion_probabilities is None


def test_future_date_in_daily_timezone_precedes_missing_baseline(
    db_session: Session,
    user: User,
) -> None:
    target_date = date(2026, 7, 28)
    daily_record(
        db_session,
        user_id=user.id,
        record_date=target_date,
        timezone="Pacific/Kiritimati",
    )

    with pytest.raises(FutureEvaluationDateError) as raised:
        prepare_risk_evaluation(
            db_session,
            user_id=user.id,
            record_date=target_date,
            now=datetime(2026, 7, 27, 9, tzinfo=UTC),
        )

    assert raised.value.time_zone == "Pacific/Kiritimati"
    assert raised.value.local_today == date(2026, 7, 27)


@pytest.mark.parametrize("metadata_kind", ["missing", "invalid"])
def test_prepare_rejects_unusable_daily_contract_without_guessing(
    db_session: Session,
    user: User,
    metadata_kind: str,
) -> None:
    target_date = date(2026, 7, 20)
    daily = daily_record(
        db_session,
        user_id=user.id,
        record_date=target_date,
    )
    if metadata_kind == "missing":
        daily.source_by_field = None
    else:
        daily.coverage_by_field = {}
    db_session.flush()

    with pytest.raises(RiskInputUnavailableError):
        prepare_risk_evaluation(
            db_session,
            user_id=user.id,
            record_date=target_date,
            now=datetime(2026, 7, 21, tzinfo=UTC),
        )


def test_prepare_distinguishes_missing_daily_and_eligible_baseline(
    db_session: Session,
    user: User,
) -> None:
    target_date = date(2026, 7, 20)
    with pytest.raises(DailyRecordNotFoundError):
        prepare_risk_evaluation(
            db_session,
            user_id=user.id,
            record_date=target_date,
            now=datetime(2026, 7, 21, tzinfo=UTC),
        )

    daily_record(
        db_session,
        user_id=user.id,
        record_date=target_date,
    )
    with pytest.raises(ReadyBaselineNotFoundError):
        prepare_risk_evaluation(
            db_session,
            user_id=user.id,
            record_date=target_date,
            now=datetime(2026, 7, 21, tzinfo=UTC),
        )


def test_store_rejects_changed_provenance_without_inserting(
    db_session: Session,
    user: User,
) -> None:
    target_date = date(2026, 7, 20)
    daily = daily_record(
        db_session,
        user_id=user.id,
        record_date=target_date,
    )
    ready_baseline(
        db_session,
        user_id=user.id,
        window_end=target_date - timedelta(days=1),
    )
    daily_id = daily.id
    db_session.commit()
    prepared = prepare_risk_evaluation(
        db_session,
        user_id=user.id,
        record_date=target_date,
        now=datetime(2026, 7, 21, tzinfo=UTC),
    )
    db_session.rollback()
    result = evaluate_prepared_risk(prepared)

    with Session(db_session.get_bind()) as concurrent_session:
        concurrent_daily = concurrent_session.get(
            BehavioralDailyRecord,
            daily_id,
        )
        assert concurrent_daily is not None
        concurrent_daily.sleep_minutes = 300
        concurrent_session.commit()

    with pytest.raises(RiskInputsChangedError):
        store_prepared_risk_evaluation(
            db_session,
            prepared=prepared,
            result=result,
        )
    db_session.rollback()

    assert evaluation_count(db_session, user_id=user.id) == 0


def test_store_rejects_deleted_selected_emotion_without_inserting(
    db_session: Session,
    user: User,
) -> None:
    target_date = date(2026, 7, 20)
    daily_record(
        db_session,
        user_id=user.id,
        record_date=target_date,
    )
    selected_emotion = emotion_result(
        db_session,
        user_id=user.id,
        record_date=target_date,
    )
    ready_baseline(
        db_session,
        user_id=user.id,
        window_end=target_date - timedelta(days=1),
    )
    emotion_id = selected_emotion.id
    db_session.commit()
    prepared = prepare_risk_evaluation(
        db_session,
        user_id=user.id,
        record_date=target_date,
        now=datetime(2026, 7, 21, tzinfo=UTC),
    )
    db_session.rollback()
    result = evaluate_prepared_risk(prepared)

    with Session(db_session.get_bind()) as concurrent_session:
        concurrent_emotion = concurrent_session.get(
            EmotionAnalysisResult,
            emotion_id,
        )
        assert concurrent_emotion is not None
        concurrent_session.delete(concurrent_emotion)
        concurrent_session.commit()

    with pytest.raises(RiskInputsChangedError):
        store_prepared_risk_evaluation(
            db_session,
            prepared=prepared,
            result=result,
        )
    db_session.rollback()

    assert evaluation_count(db_session, user_id=user.id) == 0


def test_store_requires_the_read_transaction_to_be_closed(
    db_session: Session,
    user: User,
) -> None:
    target_date = date(2026, 7, 20)
    daily_record(
        db_session,
        user_id=user.id,
        record_date=target_date,
    )
    ready_baseline(
        db_session,
        user_id=user.id,
        window_end=target_date - timedelta(days=1),
    )
    db_session.commit()
    prepared = prepare_risk_evaluation(
        db_session,
        user_id=user.id,
        record_date=target_date,
        now=datetime(2026, 7, 21, tzinfo=UTC),
    )
    result = evaluate_prepared_risk(prepared)

    with pytest.raises(
        RuntimeError,
        match="requires a fresh transaction",
    ):
        store_prepared_risk_evaluation(
            db_session,
            prepared=prepared,
            result=result,
        )

    assert evaluation_count(db_session, user_id=user.id) == 0


@pytest.mark.parametrize(
    ("repository_call", "id_keyword"),
    [
        (get_daily_record, "record_id"),
        (get_emotion_result, "result_id"),
        (get_baseline, "baseline_id"),
    ],
)
def test_provenance_requeries_lock_rows_on_postgresql(
    repository_call: Callable[..., object],
    id_keyword: str,
) -> None:
    session = MagicMock(spec=Session)
    kwargs = {
        "user_id": "user-id",
        id_keyword: "provenance-id",
        "for_update": True,
    }

    repository_call(session, **kwargs)

    statement = session.scalar.call_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert sql.rstrip().endswith("FOR UPDATE")
