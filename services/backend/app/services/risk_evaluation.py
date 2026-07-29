from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domain.risk.engine import BurnoutRiskEngine
from app.domain.risk.models import (
    BurnoutRiskEvaluationRequest,
    BurnoutRiskEvaluationResponse,
)
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    EmotionAnalysisResult,
    PersistenceBaselineStatus,
)
from app.repositories.baselines import (
    get_baseline,
    get_latest_ready_baseline_before,
)
from app.repositories.behavioral_records import (
    get_daily_record,
    get_daily_record_by_date,
)
from app.repositories.emotion_results import (
    get_emotion_result,
    get_latest_emotion_result_by_date,
)
from app.repositories.risk_evaluations import create_risk_evaluation
from app.schemas.behavioral_records import DailyRecordRead
from app.services.behavioral_record_mapper import (
    DailyRecordMetadataUnavailableError,
    to_daily_record_read,
)
from app.services.risk_adapter import build_risk_request


class DailyRecordNotFoundError(LookupError):
    """The requested user has no Daily Record for the evaluation date."""


class ReadyBaselineNotFoundError(RuntimeError):
    """No eligible READY baseline exists before the evaluation date."""


class RiskInputUnavailableError(RuntimeError):
    """Persisted input cannot be represented by its public contract."""


class RiskInputsChangedError(RuntimeError):
    """Prepared provenance was deleted or changed before persistence."""


class FutureEvaluationDateError(ValueError):
    """The requested date is in the future in the Daily Record timezone."""

    def __init__(
        self,
        *,
        record_date: date,
        time_zone: str,
        local_today: date,
    ) -> None:
        self.record_date = record_date
        self.time_zone = time_zone
        self.local_today = local_today
        super().__init__(
            f"{record_date.isoformat()} is in the future for "
            f"{time_zone} (local date {local_today.isoformat()})"
        )


@dataclass(frozen=True)
class PreparedRiskEvaluation:
    """Immutable engine input and provenance captured by the read phase."""

    user_id: str
    record_date: date
    time_zone: str
    daily_record_id: str
    emotion_result_id: str | None
    baseline_id: str
    request: BurnoutRiskEvaluationRequest = field(repr=False)
    daily_snapshot: str = field(repr=False)
    emotion_snapshot: str | None = field(repr=False)
    baseline_snapshot: str = field(repr=False)

    @property
    def emotion_analysis_id(self) -> str | None:
        """Expose the public provenance spelling without duplicating state."""

        return self.emotion_result_id


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _snapshot(payload: Any) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        default=_json_default,
        separators=(",", ":"),
        sort_keys=True,
    )


def _daily_snapshot(
    daily_record: BehavioralDailyRecord,
) -> tuple[DailyRecordRead, str]:
    contract = to_daily_record_read(daily_record)
    return contract, _snapshot(
        {
            "contract": contract.model_dump(mode="json"),
            "subjective_stress": (
                float(daily_record.subjective_stress)
                if daily_record.subjective_stress is not None
                else None
            ),
            "updated_at": daily_record.updated_at,
        }
    )


def _emotion_snapshot(
    emotion_result: EmotionAnalysisResult | None,
) -> str | None:
    if emotion_result is None:
        return None
    return _snapshot(
        {
            "record_date": emotion_result.record_date,
            "analyzed_at": emotion_result.analyzed_at,
            "created_at": emotion_result.created_at,
            "taxonomy_version": emotion_result.taxonomy_version,
            "model_version": emotion_result.model_version,
            "predicted_emotion": emotion_result.predicted_emotion,
            "emotion": emotion_result.emotion,
            "confidence": float(emotion_result.confidence),
            "margin": (
                float(emotion_result.margin)
                if emotion_result.margin is not None
                else None
            ),
            "provisional": emotion_result.provisional,
            "is_uncertain": emotion_result.is_uncertain,
            "probabilities": emotion_result.probabilities,
            "threshold_version": emotion_result.threshold_version,
            "input_hash": emotion_result.input_hash,
        }
    )


def _baseline_snapshot(baseline: BehavioralBaseline) -> str:
    def normalized(value: float | None) -> float | None:
        return float(value) if value is not None else None

    return _snapshot(
        {
            "window_start": baseline.window_start,
            "window_end": baseline.window_end,
            "sample_days": baseline.sample_days,
            "sleep_minutes": normalized(baseline.sleep_minutes),
            "study_work_minutes": normalized(
                baseline.study_work_minutes
            ),
            "rest_minutes": normalized(baseline.rest_minutes),
            "exercise_minutes": normalized(baseline.exercise_minutes),
            "schedule_count": normalized(baseline.schedule_count),
            "subjective_stress": normalized(baseline.subjective_stress),
            "subjective_fatigue": normalized(baseline.subjective_fatigue),
            "negative_emotion_probability": (
                normalized(baseline.negative_emotion_probability)
            ),
            "status": baseline.status,
            "algorithm_version": baseline.algorithm_version,
            "created_at": baseline.created_at,
        }
    )


def _local_today(*, time_zone: str, now: datetime | None) -> date:
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return instant.astimezone(ZoneInfo(time_zone)).date()


def prepare_risk_evaluation(
    session: Session,
    *,
    user_id: str,
    record_date: date,
    now: datetime | None = None,
) -> PreparedRiskEvaluation:
    """Read and freeze all user-scoped inputs without running the engine."""

    daily_record = get_daily_record_by_date(
        session,
        user_id=user_id,
        record_date=record_date,
    )
    if daily_record is None:
        raise DailyRecordNotFoundError

    try:
        daily_contract, daily_snapshot = _daily_snapshot(daily_record)
    except (DailyRecordMetadataUnavailableError, ValidationError) as exc:
        raise RiskInputUnavailableError(
            "daily record does not satisfy the shared contract"
        ) from exc

    local_today = _local_today(
        time_zone=daily_contract.time_zone,
        now=now,
    )
    if record_date > local_today:
        raise FutureEvaluationDateError(
            record_date=record_date,
            time_zone=daily_contract.time_zone,
            local_today=local_today,
        )

    emotion_result = get_latest_emotion_result_by_date(
        session,
        user_id=user_id,
        record_date=record_date,
    )
    baseline = get_latest_ready_baseline_before(
        session,
        user_id=user_id,
        evaluation_date=record_date,
        minimum_sample_days=7,
    )
    if baseline is None:
        raise ReadyBaselineNotFoundError

    request = build_risk_request(
        user_id=user_id,
        daily_record=daily_record,
        emotion_result=emotion_result,
        baseline=baseline,
        daily_contract=daily_contract,
    )
    return PreparedRiskEvaluation(
        user_id=user_id,
        record_date=record_date,
        time_zone=daily_contract.time_zone,
        daily_record_id=daily_record.id,
        emotion_result_id=(
            emotion_result.id if emotion_result is not None else None
        ),
        baseline_id=baseline.id,
        request=request,
        daily_snapshot=daily_snapshot,
        emotion_snapshot=_emotion_snapshot(emotion_result),
        baseline_snapshot=_baseline_snapshot(baseline),
    )


def evaluate_prepared_risk(
    prepared: PreparedRiskEvaluation,
    *,
    engine: BurnoutRiskEngine | None = None,
) -> BurnoutRiskEvaluationResponse:
    """Run the pure rules engine against a detached immutable snapshot."""

    return (engine or BurnoutRiskEngine()).evaluate(prepared.request)


def _raise_inputs_changed() -> NoReturn:
    raise RiskInputsChangedError(
        "risk evaluation inputs changed before the result could be stored"
    )


def store_prepared_risk_evaluation(
    session: Session,
    *,
    prepared: PreparedRiskEvaluation,
    result: BurnoutRiskEvaluationResponse,
) -> BurnoutRiskEvaluation:
    """Revalidate provenance and stage one append-only evaluation insert."""

    if session.in_transaction():
        raise RuntimeError(
            "risk evaluation write phase requires a fresh transaction"
        )

    daily_record = get_daily_record(
        session,
        user_id=prepared.user_id,
        record_id=prepared.daily_record_id,
        for_update=True,
    )
    baseline = get_baseline(
        session,
        user_id=prepared.user_id,
        baseline_id=prepared.baseline_id,
        for_update=True,
    )
    emotion_result = (
        get_emotion_result(
            session,
            user_id=prepared.user_id,
            result_id=prepared.emotion_result_id,
            for_update=True,
        )
        if prepared.emotion_result_id is not None
        else None
    )
    if daily_record is None or baseline is None:
        _raise_inputs_changed()
    if prepared.emotion_result_id is not None and emotion_result is None:
        _raise_inputs_changed()

    if (
        daily_record.record_date != prepared.record_date
        or baseline.status is not PersistenceBaselineStatus.READY
        or baseline.sample_days < 7
        or baseline.window_end >= prepared.record_date
        or (
            emotion_result is not None
            and emotion_result.record_date != prepared.record_date
        )
    ):
        _raise_inputs_changed()

    try:
        daily_contract, daily_snapshot = _daily_snapshot(daily_record)
        reloaded_request = build_risk_request(
            user_id=prepared.user_id,
            daily_record=daily_record,
            emotion_result=emotion_result,
            baseline=baseline,
            daily_contract=daily_contract,
        )
        emotion_snapshot = _emotion_snapshot(emotion_result)
        baseline_snapshot = _baseline_snapshot(baseline)
    except (
        DailyRecordMetadataUnavailableError,
        ValidationError,
        ValueError,
    ) as exc:
        raise RiskInputsChangedError(
            "risk evaluation inputs became invalid before persistence"
        ) from exc

    if (
        daily_snapshot != prepared.daily_snapshot
        or emotion_snapshot != prepared.emotion_snapshot
        or baseline_snapshot != prepared.baseline_snapshot
        or reloaded_request != prepared.request
    ):
        _raise_inputs_changed()

    return create_risk_evaluation(
        session,
        user_id=prepared.user_id,
        result=result,
        daily_record=daily_record,
        emotion_result=emotion_result,
        baseline=baseline,
        record_date=prepared.record_date,
    )


def evaluate_and_store(
    session: Session,
    *,
    user_id: str,
    daily_record: BehavioralDailyRecord,
    emotion_result: EmotionAnalysisResult | None,
    baseline: BehavioralBaseline | None,
    engine: BurnoutRiskEngine | None = None,
) -> tuple[BurnoutRiskEvaluation, BurnoutRiskEvaluationResponse]:
    request = build_risk_request(
        user_id=user_id,
        daily_record=daily_record,
        emotion_result=emotion_result,
        baseline=baseline,
    )
    result = (engine or BurnoutRiskEngine()).evaluate(request)
    evaluation = create_risk_evaluation(
        session,
        user_id=user_id,
        result=result,
        daily_record=daily_record,
        emotion_result=emotion_result,
        baseline=baseline,
    )
    return evaluation, result


__all__ = [
    "DailyRecordNotFoundError",
    "FutureEvaluationDateError",
    "PreparedRiskEvaluation",
    "ReadyBaselineNotFoundError",
    "RiskInputUnavailableError",
    "RiskInputsChangedError",
    "evaluate_and_store",
    "evaluate_prepared_risk",
    "prepare_risk_evaluation",
    "store_prepared_risk_evaluation",
]
