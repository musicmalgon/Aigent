from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.risk.models import EmotionProbabilities
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    EmotionAnalysisResult,
    PersistenceBaselineStatus,
)
from app.repositories.baselines import create_baseline

BASELINE_ALGORITHM_VERSION = "behavioral-baseline-mean-v1"
DEFAULT_WINDOW_DAYS = 14
MINIMUM_SAMPLE_DAYS = 7

_DAILY_METRICS = (
    "sleep_minutes",
    "study_work_minutes",
    "rest_minutes",
    "exercise_minutes",
    "schedule_count",
    "subjective_stress",
    "subjective_fatigue",
)


@dataclass(frozen=True)
class BaselineCalculation:
    window_start: date
    window_end: date
    sample_days: int
    sleep_minutes: float | None
    study_work_minutes: float | None
    rest_minutes: float | None
    exercise_minutes: float | None
    schedule_count: float | None
    subjective_stress: float | None
    subjective_fatigue: float | None
    negative_emotion_probability: float | None
    status: PersistenceBaselineStatus
    algorithm_version: str = BASELINE_ALGORITHM_VERSION


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _latest_emotion_by_date(
    emotion_results: list[EmotionAnalysisResult],
    *,
    window_start: date,
    window_end: date,
) -> dict[date, EmotionAnalysisResult]:
    candidates = sorted(
        (
            item
            for item in emotion_results
            if item.record_date is not None
            and window_start <= item.record_date <= window_end
        ),
        key=lambda item: (
            item.analyzed_at,
            item.created_at,
            item.id,
        ),
        reverse=True,
    )
    latest: dict[date, EmotionAnalysisResult] = {}
    for item in candidates:
        assert item.record_date is not None
        latest.setdefault(item.record_date, item)
    return latest


def calculate_baseline(
    *,
    daily_records: list[BehavioralDailyRecord],
    emotion_results: list[EmotionAnalysisResult],
    window_end: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    minimum_sample_days: int = MINIMUM_SAMPLE_DAYS,
    today: date | None = None,
) -> BaselineCalculation:
    if not 14 <= window_days <= 28:
        raise ValueError("baseline window_days must be between 14 and 28")
    if minimum_sample_days < 1 or minimum_sample_days > window_days:
        raise ValueError("minimum_sample_days must fit inside the window")
    if window_end > (today or date.today()):
        raise ValueError("baseline window cannot end in the future")

    window_start = window_end - timedelta(days=window_days - 1)
    records = [
        item
        for item in daily_records
        if window_start <= item.record_date <= window_end
    ]
    values_by_metric: dict[str, list[float]] = {
        metric: [] for metric in _DAILY_METRICS
    }
    valid_dates: set[date] = set()
    for record in records:
        present = False
        for metric in _DAILY_METRICS:
            value = getattr(record, metric)
            if value is not None:
                values_by_metric[metric].append(float(value))
                present = True
        if present:
            valid_dates.add(record.record_date)

    negative_probabilities: list[float] = []
    for record_date, result in _latest_emotion_by_date(
        emotion_results,
        window_start=window_start,
        window_end=window_end,
    ).items():
        probabilities = EmotionProbabilities.model_validate(
            result.probabilities
        )
        negative_probabilities.append(probabilities.negative_probability)
        valid_dates.add(record_date)

    sample_days = len(valid_dates)
    status = (
        PersistenceBaselineStatus.READY
        if sample_days >= minimum_sample_days
        else PersistenceBaselineStatus.INSUFFICIENT
    )
    return BaselineCalculation(
        window_start=window_start,
        window_end=window_end,
        sample_days=sample_days,
        sleep_minutes=_mean(values_by_metric["sleep_minutes"]),
        study_work_minutes=_mean(
            values_by_metric["study_work_minutes"]
        ),
        rest_minutes=_mean(values_by_metric["rest_minutes"]),
        exercise_minutes=_mean(values_by_metric["exercise_minutes"]),
        schedule_count=_mean(values_by_metric["schedule_count"]),
        subjective_stress=_mean(
            values_by_metric["subjective_stress"]
        ),
        subjective_fatigue=_mean(
            values_by_metric["subjective_fatigue"]
        ),
        negative_emotion_probability=_mean(negative_probabilities),
        status=status,
    )


def calculate_and_store_baseline(
    session: Session,
    *,
    user_id: str,
    window_end: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    minimum_sample_days: int = MINIMUM_SAMPLE_DAYS,
    today: date | None = None,
) -> BehavioralBaseline:
    window_start = window_end - timedelta(days=window_days - 1)
    daily_records = list(
        session.scalars(
            select(BehavioralDailyRecord).where(
                BehavioralDailyRecord.user_id == user_id,
                BehavioralDailyRecord.record_date >= window_start,
                BehavioralDailyRecord.record_date <= window_end,
            )
        )
    )
    emotion_results = list(
        session.scalars(
            select(EmotionAnalysisResult).where(
                EmotionAnalysisResult.user_id == user_id,
                EmotionAnalysisResult.record_date.is_not(None),
                EmotionAnalysisResult.record_date >= window_start,
                EmotionAnalysisResult.record_date <= window_end,
            )
        )
    )
    calculation = calculate_baseline(
        daily_records=daily_records,
        emotion_results=emotion_results,
        window_end=window_end,
        window_days=window_days,
        minimum_sample_days=minimum_sample_days,
        today=today,
    )
    baseline = BehavioralBaseline(
        user_id=user_id,
        **calculation.__dict__,
    )
    return create_baseline(session, baseline)


__all__ = [
    "BASELINE_ALGORITHM_VERSION",
    "BaselineCalculation",
    "DEFAULT_WINDOW_DAYS",
    "MINIMUM_SAMPLE_DAYS",
    "calculate_and_store_baseline",
    "calculate_baseline",
]
