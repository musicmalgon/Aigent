from __future__ import annotations

from app.domain.risk.models import (
    BurnoutRiskEvaluationRequest,
    CurrentRiskSignals,
    EmotionProbabilities,
    PersonalBaseline,
)
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    EmotionAnalysisResult,
)
from app.repositories import PersistenceScopeError


def _validate_scope(
    *,
    user_id: str,
    daily_record: BehavioralDailyRecord,
    emotion_result: EmotionAnalysisResult | None,
    baseline: BehavioralBaseline | None,
) -> None:
    entities = (
        ("daily record", daily_record),
        ("emotion result", emotion_result),
        ("baseline", baseline),
    )
    for name, entity in entities:
        if entity is not None and entity.user_id != user_id:
            raise PersistenceScopeError(
                f"{name} does not belong to the requested user"
            )
    if (
        emotion_result is not None
        and emotion_result.record_date is not None
        and emotion_result.record_date != daily_record.record_date
    ):
        raise ValueError("emotion result date must match the daily record date")
    if baseline is not None and baseline.window_end >= daily_record.record_date:
        raise ValueError("baseline window must end before the current record")


def build_risk_request(
    *,
    user_id: str,
    daily_record: BehavioralDailyRecord,
    emotion_result: EmotionAnalysisResult | None,
    baseline: BehavioralBaseline | None,
) -> BurnoutRiskEvaluationRequest:
    _validate_scope(
        user_id=user_id,
        daily_record=daily_record,
        emotion_result=emotion_result,
        baseline=baseline,
    )
    emotion_probabilities = (
        EmotionProbabilities.model_validate(emotion_result.probabilities)
        if emotion_result is not None
        else None
    )
    current = CurrentRiskSignals(
        sleep_minutes=daily_record.sleep_minutes,
        work_or_study_minutes=daily_record.study_work_minutes,
        rest_minutes=daily_record.rest_minutes,
        exercise_minutes=daily_record.exercise_minutes,
        schedule_count=daily_record.schedule_count,
        subjective_stress=daily_record.subjective_stress,
        subjective_fatigue=daily_record.subjective_fatigue,
        emotion_probabilities=emotion_probabilities,
        emotion_confidence=(
            emotion_result.confidence
            if emotion_result is not None
            else None
        ),
        emotion_uncertain=(
            emotion_result.is_uncertain
            if emotion_result is not None
            else None
        ),
    )
    personal_baseline = (
        PersonalBaseline(
            sleep_minutes=baseline.sleep_minutes,
            work_or_study_minutes=baseline.study_work_minutes,
            rest_minutes=baseline.rest_minutes,
            exercise_minutes=baseline.exercise_minutes,
            schedule_count=baseline.schedule_count,
            subjective_stress=baseline.subjective_stress,
            subjective_fatigue=baseline.subjective_fatigue,
            negative_emotion_probability=(
                baseline.negative_emotion_probability
            ),
            sample_days=baseline.sample_days,
        )
        if baseline is not None
        else None
    )
    return BurnoutRiskEvaluationRequest(
        current=current,
        baseline=personal_baseline,
    )


__all__ = ["build_risk_request"]
