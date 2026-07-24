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
    list_emotion_results,
)
from app.schemas.persistence import EmotionLabel, EmotionResultCreate

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
