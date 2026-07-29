from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.persistence import BehavioralBaseline, PersistenceBaselineStatus
from app.models.user import User
from app.repositories.baselines import (
    get_latest_ready_baseline,
    get_latest_ready_baseline_before,
    list_baselines,
)
from app.services.baselines import (
    BASELINE_ALGORITHM_VERSION,
    calculate_and_store_baseline,
    calculate_baseline,
)

from .helpers import daily_record, emotion_result


def stored_baseline(
    session: Session,
    *,
    user_id: str,
    window_end: date,
    sample_days: int = 7,
    status: PersistenceBaselineStatus = PersistenceBaselineStatus.READY,
    created_at: datetime | None = None,
) -> BehavioralBaseline:
    item = BehavioralBaseline(
        user_id=user_id,
        window_start=window_end - timedelta(days=13),
        window_end=window_end,
        sample_days=sample_days,
        status=status,
        algorithm_version="behavioral-baseline-test-v1",
        created_at=created_at or datetime.now(UTC),
    )
    session.add(item)
    session.flush()
    return item


def test_fourteen_day_mean_missing_denominators_and_emotion(
    db_session: Session,
    user: User,
) -> None:
    window_end = date(2026, 7, 20)
    for offset in range(7):
        record_date = window_end - timedelta(days=offset)
        daily_record(
            db_session,
            user_id=user.id,
            record_date=record_date,
            sleep_minutes=420 + offset * 10,
            rest_minutes=None if offset < 2 else 60,
        )
        emotion_result(
            db_session,
            user_id=user.id,
            record_date=record_date,
            joy=0.2,
            analyzed_at=datetime(
                2026,
                7,
                20 - offset,
                8,
                tzinfo=UTC,
            ),
        )

    baseline = calculate_and_store_baseline(
        db_session,
        user_id=user.id,
        window_end=window_end,
        today=window_end,
    )

    assert baseline.window_start == date(2026, 7, 7)
    assert baseline.sample_days == 7
    assert baseline.status is PersistenceBaselineStatus.READY
    assert baseline.sleep_minutes == 450
    assert baseline.rest_minutes == 60
    assert baseline.negative_emotion_probability == 0.8
    assert baseline.algorithm_version == BASELINE_ALGORITHM_VERSION
    assert get_latest_ready_baseline(db_session, user_id=user.id) is baseline


def test_six_days_produces_insufficient_baseline(
    db_session: Session,
    user: User,
) -> None:
    window_end = date(2026, 7, 20)
    for offset in range(6):
        daily_record(
            db_session,
            user_id=user.id,
            record_date=window_end - timedelta(days=offset),
        )

    baseline = calculate_and_store_baseline(
        db_session,
        user_id=user.id,
        window_end=window_end,
        today=window_end,
    )

    assert baseline.sample_days == 6
    assert baseline.status is PersistenceBaselineStatus.INSUFFICIENT
    assert get_latest_ready_baseline(db_session, user_id=user.id) is None
    assert list_baselines(db_session, user_id=user.id) == [baseline]


def test_latest_ready_baseline_before_prevents_future_data_leakage(
    db_session: Session,
    user: User,
    other_user: User,
) -> None:
    evaluation_date = date(2026, 7, 20)
    created_at = datetime(2026, 7, 19, 12, tzinfo=UTC)
    stored_baseline(
        db_session,
        user_id=user.id,
        window_end=evaluation_date - timedelta(days=2),
        created_at=created_at + timedelta(hours=3),
    )
    first = stored_baseline(
        db_session,
        user_id=user.id,
        window_end=evaluation_date - timedelta(days=1),
        created_at=created_at,
    )
    second = stored_baseline(
        db_session,
        user_id=user.id,
        window_end=evaluation_date - timedelta(days=1),
        created_at=created_at,
    )
    stored_baseline(
        db_session,
        user_id=user.id,
        window_end=evaluation_date - timedelta(days=1),
        sample_days=6,
        created_at=created_at + timedelta(hours=2),
    )
    stored_baseline(
        db_session,
        user_id=user.id,
        window_end=evaluation_date - timedelta(days=1),
        status=PersistenceBaselineStatus.INSUFFICIENT,
        created_at=created_at + timedelta(hours=2),
    )
    stored_baseline(
        db_session,
        user_id=user.id,
        window_end=evaluation_date,
        created_at=created_at + timedelta(hours=3),
    )
    stored_baseline(
        db_session,
        user_id=other_user.id,
        window_end=evaluation_date - timedelta(days=1),
        created_at=created_at + timedelta(hours=4),
    )

    expected = max((first, second), key=lambda item: item.id)
    assert (
        get_latest_ready_baseline_before(
            db_session,
            user_id=user.id,
            evaluation_date=evaluation_date,
        )
        is expected
    )
    assert (
        get_latest_ready_baseline_before(
            db_session,
            user_id=user.id,
            evaluation_date=evaluation_date,
            minimum_sample_days=8,
        )
        is None
    )


def test_latest_emotion_on_same_date_is_used(
    db_session: Session,
    user: User,
) -> None:
    record_date = date(2026, 7, 20)
    daily_record(db_session, user_id=user.id, record_date=record_date)
    emotion_result(
        db_session,
        user_id=user.id,
        record_date=record_date,
        joy=0.8,
        analyzed_at=datetime(2026, 7, 20, 8, tzinfo=UTC),
    )
    emotion_result(
        db_session,
        user_id=user.id,
        record_date=record_date,
        joy=0.1,
        analyzed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )

    baseline = calculate_and_store_baseline(
        db_session,
        user_id=user.id,
        window_end=record_date,
        today=record_date,
    )

    assert baseline.negative_emotion_probability == 0.9
    assert baseline.sample_days == 1


def test_future_window_and_invalid_window_size_are_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        calculate_baseline(
            daily_records=[],
            emotion_results=[],
            window_end=date(2026, 7, 21),
            today=date(2026, 7, 20),
        )

    with pytest.raises(ValueError, match="between 14 and 28"):
        calculate_baseline(
            daily_records=[],
            emotion_results=[],
            window_end=date(2026, 7, 20),
            window_days=7,
            today=date(2026, 7, 20),
        )
