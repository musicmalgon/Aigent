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
from app.schemas.behavioral_records import DailyRecordRead


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
    daily_contract: DailyRecordRead | None = None,
) -> BurnoutRiskEvaluationRequest:
    _validate_scope(
        user_id=user_id,
        daily_record=daily_record,
        emotion_result=emotion_result,
        baseline=baseline,
    )
    if daily_contract is not None:
        if daily_contract.user_id != user_id:
            raise PersistenceScopeError(
                "daily record contract does not belong to the requested user"
            )
        if daily_contract.date != daily_record.record_date:
            raise ValueError(
                "daily record contract date must match the persisted record"
            )

    emotion_probabilities = (
        EmotionProbabilities.model_validate(emotion_result.probabilities)
        if emotion_result is not None
        else None
    )
    sleep_minutes = (
        daily_contract.sleep_minutes
        if daily_contract is not None
        else daily_record.sleep_minutes
    )
    work_or_study_minutes = (
        daily_contract.work_or_study_minutes
        if daily_contract is not None
        else daily_record.study_work_minutes
    )
    rest_minutes = (
        daily_contract.rest_minutes
        if daily_contract is not None
        else daily_record.rest_minutes
    )
    exercise_minutes = (
        daily_contract.exercise_minutes
        if daily_contract is not None
        else daily_record.exercise_minutes
    )
    schedule_count = (
        daily_contract.schedule_count
        if daily_contract is not None
        else daily_record.schedule_count
    )
    subjective_fatigue = (
        daily_contract.subjective_fatigue
        if daily_contract is not None
        else daily_record.subjective_fatigue
    )
    current = CurrentRiskSignals(
        sleep_minutes=sleep_minutes,
        work_or_study_minutes=work_or_study_minutes,
        rest_minutes=rest_minutes,
        exercise_minutes=exercise_minutes,
        schedule_count=schedule_count,
        subjective_stress=daily_record.subjective_stress,
        subjective_fatigue=subjective_fatigue,
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
