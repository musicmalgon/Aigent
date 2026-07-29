from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.models.persistence import EmotionAnalysisResult
from app.models.user import User
from app.repositories.emotion_results import (
    create_emotion_result,
    get_emotion_result,
    get_latest_emotion_result,
    get_latest_emotion_result_by_date,
    list_emotion_results,
)
from app.schemas.persistence import (
    EmotionLabel,
    EmotionResultCreate,
    EmotionTaxonomyVersion,
    EmotionV2Label,
)
from app.services.emotion_analysis import to_emotion_analysis_read

from .helpers import probabilities


def payload(
    *,
    analyzed_at: datetime,
) -> EmotionResultCreate:
    return EmotionResultCreate(
        record_date=date(2026, 7, 20),
        analyzed_at=analyzed_at,
        model_version="coarse-emotion-v1",
        predicted_emotion=EmotionLabel.ANXIETY,
        confidence=0.8,
        is_uncertain=False,
        probabilities=probabilities(),
        input_hash="sha256-like-irreversible-hash",
    )


def test_create_latest_list_and_scope(
    db_session: Session,
    user: User,
    other_user: User,
) -> None:
    earlier = datetime(2026, 7, 20, 9, tzinfo=UTC)
    first = create_emotion_result(
        db_session,
        user_id=user.id,
        payload=payload(analyzed_at=earlier),
    )
    latest = create_emotion_result(
        db_session,
        user_id=user.id,
        payload=payload(analyzed_at=earlier + timedelta(hours=1)),
    )

    assert get_latest_emotion_result(db_session, user_id=user.id) is latest
    assert list_emotion_results(db_session, user_id=user.id) == [
        latest,
        first,
    ]
    assert (
        get_emotion_result(
            db_session,
            user_id=other_user.id,
            result_id=latest.id,
        )
        is None
    )
    assert latest.input_hash == "sha256-like-irreversible-hash"


def test_v1_and_v2_rows_round_trip_without_reinterpreting_labels(
    db_session: Session,
    user: User,
) -> None:
    analyzed_at = datetime(2026, 7, 20, 9, tzinfo=UTC)
    v1 = create_emotion_result(
        db_session,
        user_id=user.id,
        payload=EmotionResultCreate(
            record_date=date(2026, 7, 19),
            analyzed_at=analyzed_at,
            model_version="coarse-v1",
            predicted_emotion=EmotionLabel.HURT,
            confidence=0.8,
            is_uncertain=False,
            probabilities=probabilities(),
        ),
    )
    v2_probabilities = {
        EmotionV2Label.ANGER: 0.05,
        EmotionV2Label.JOY: 0.05,
        EmotionV2Label.ANXIETY: 0.05,
        EmotionV2Label.EMBARRASSMENT: 0.05,
        EmotionV2Label.SADNESS: 0.10,
        EmotionV2Label.LETHARGY: 0.70,
    }
    v2 = create_emotion_result(
        db_session,
        user_id=user.id,
        payload=EmotionResultCreate(
            record_date=date(2026, 7, 20),
            analyzed_at=analyzed_at + timedelta(hours=1),
            taxonomy_version=EmotionTaxonomyVersion.V2,
            model_version="coarse-v2",
            predicted_emotion=EmotionV2Label.LETHARGY,
            emotion=EmotionV2Label.LETHARGY,
            confidence=0.70,
            margin=0.60,
            provisional=False,
            is_uncertain=False,
            probabilities=v2_probabilities,
            threshold_version="mvp-v1",
        ),
    )
    db_session.flush()

    v1_read = to_emotion_analysis_read(v1)
    v2_read = to_emotion_analysis_read(v2)

    assert v1_read.taxonomy_version is EmotionTaxonomyVersion.V1
    assert v1_read.predicted_emotion is EmotionLabel.HURT
    assert v1_read.emotion is EmotionLabel.HURT
    assert v2_read.taxonomy_version is EmotionTaxonomyVersion.V2
    assert v2_read.predicted_emotion is EmotionV2Label.LETHARGY
    assert v2_read.emotion is EmotionV2Label.LETHARGY
    assert [item.id for item in list_emotion_results(db_session, user_id=user.id)] == [
        v2.id,
        v1.id,
    ]


def test_latest_emotion_by_date_is_scoped_and_deterministic(
    db_session: Session,
    user: User,
    other_user: User,
) -> None:
    target_date = date(2026, 7, 20)
    analyzed_at = datetime(2026, 7, 20, 9, tzinfo=UTC)
    created_at = analyzed_at + timedelta(minutes=1)
    first = create_emotion_result(
        db_session,
        user_id=user.id,
        payload=payload(analyzed_at=analyzed_at),
    )
    second = create_emotion_result(
        db_session,
        user_id=user.id,
        payload=payload(analyzed_at=analyzed_at),
    )
    for result in (first, second):
        result.created_at = created_at

    different_date = create_emotion_result(
        db_session,
        user_id=user.id,
        payload=payload(analyzed_at=analyzed_at + timedelta(hours=3)).model_copy(
            update={"record_date": target_date + timedelta(days=1)}
        ),
    )
    undated = create_emotion_result(
        db_session,
        user_id=user.id,
        payload=payload(analyzed_at=analyzed_at + timedelta(hours=4)).model_copy(
            update={"record_date": None}
        ),
    )
    other = create_emotion_result(
        db_session,
        user_id=other_user.id,
        payload=payload(analyzed_at=analyzed_at + timedelta(hours=5)),
    )
    db_session.flush()

    expected = max((first, second), key=lambda result: result.id)
    assert (
        get_latest_emotion_result_by_date(
            db_session,
            user_id=user.id,
            record_date=target_date,
        )
        is expected
    )
    assert (
        get_latest_emotion_result_by_date(
            db_session,
            user_id=user.id,
            record_date=target_date + timedelta(days=2),
        )
        is None
    )
    assert different_date.record_date != target_date
    assert undated.record_date is None
    assert other.user_id != user.id


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence": 1.1},
        {"confidence": float("nan")},
        {"predicted_emotion": "unknown"},
        {
            "probabilities": {
                EmotionLabel.JOY: 0.5,
                EmotionLabel.ANXIETY: 0.5,
            }
        },
        {"probabilities": {**probabilities(), EmotionLabel.JOY: 0.9}},
        {"analyzed_at": datetime(2026, 7, 20, 9)},
    ],
)
def test_emotion_result_validation(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "analyzed_at": datetime(2026, 7, 20, 9, tzinfo=UTC),
        "model_version": "coarse-emotion-v1",
        "predicted_emotion": EmotionLabel.ANXIETY,
        "confidence": 0.8,
        "is_uncertain": False,
        "probabilities": probabilities(),
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        EmotionResultCreate.model_validate(values)


def test_json_storage_rejects_nan_even_when_orm_is_used_directly(
    db_session: Session,
    user: User,
) -> None:
    invalid = EmotionAnalysisResult(
        user_id=user.id,
        analyzed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
        model_version="coarse-emotion-v1",
        predicted_emotion="불안",
        confidence=0.8,
        is_uncertain=False,
        probabilities={
            "기쁨": float("nan"),
            "불안": 0.2,
            "당황": 0.2,
            "분노": 0.2,
            "슬픔": 0.2,
            "상처": 0.2,
        },
    )
    db_session.add(invalid)

    with pytest.raises(StatementError, match="NaN or Infinity"):
        db_session.flush()
    db_session.rollback()
