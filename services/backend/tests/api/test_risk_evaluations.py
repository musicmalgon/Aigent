from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api import risk_evaluations as api_module
from app.api.deps import get_ai_service_client
from app.clients.ai import (
    AIServiceClient,
    CoarseEmotionLabel,
    CoarseEmotionRequest,
    CoarseEmotionResponse,
    CoarseEmotionTopPrediction,
    UncertaintyReason,
)
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
from app.schemas.persistence import EmotionLabel
from app.services import risk_evaluation as service_module
from app.services.risk_evaluation import (
    DailyRecordNotFoundError,
    FutureEvaluationDateError,
    PreparedRiskEvaluation,
    ReadyBaselineNotFoundError,
    RiskInputsChangedError,
    RiskInputUnavailableError,
)
from tests.daily_record_contract import canonical_daily_record_payload

BASE_PATH = "/api/v1/risk-evaluations"
PASSWORD = "correct-horse-battery-staple1!"
CONTRACT_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "contracts"
    / "schemas"
    / "burnout_risk_evaluation_response.schema.json"
)


class FakeAIServiceClient:
    async def classify_emotion(
        self,
        request: CoarseEmotionRequest,
    ) -> CoarseEmotionResponse:
        del request
        probabilities = {
            label: (
                0.7 if label is CoarseEmotionLabel.JOY else 0.06
            )
            for label in CoarseEmotionLabel
        }
        return CoarseEmotionResponse(
            taxonomy_version="v2",
            model_version="coarse-test-v2",
            threshold_version="mvp-v1",
            predicted_emotion=CoarseEmotionLabel.JOY,
            predicted_label_id=1,
            emotion=CoarseEmotionLabel.JOY,
            confidence=0.7,
            margin=0.64,
            provisional=False,
            is_uncertain=False,
            uncertainty_reason=None,
            probabilities=probabilities,
            top_predictions=[
                CoarseEmotionTopPrediction(
                    emotion=CoarseEmotionLabel.JOY,
                    label_id=1,
                    probability=0.7,
                )
            ],
            latency_ms=1.0,
        )


class NeutralGateAIServiceClient:
    async def classify_emotion(
        self,
        request: CoarseEmotionRequest,
    ) -> CoarseEmotionResponse:
        del request
        return CoarseEmotionResponse(
            taxonomy_version="v2",
            model_version="coarse-test-v2",
            threshold_version="mvp-v2-neutral-gate",
            predicted_emotion=None,
            predicted_label_id=None,
            emotion=None,
            confidence=None,
            margin=None,
            provisional=True,
            is_uncertain=True,
            uncertainty_reason=UncertaintyReason.NEUTRAL_GATE,
            probabilities=None,
            top_predictions=None,
            neutral_gate_decision="neutral",
            neutral_gate_score=0.96,
            neutral_gate_model_version="neutral-gate-test-v1",
            neutral_gate_threshold=0.62,
            latency_ms=1.0,
        )


def authenticated_user(
    client: TestClient,
    *,
    email: str = "risk-api@example.com",
) -> tuple[dict[str, str], str]:
    signup = client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    # 이 파일의 일부 테스트는 생활기록/감정분석 쓰기 API를 직접 호출한다.
    # 두 API 모두 동의를 요구하므로 헬퍼에서 미리 부여해 둔다.
    for consent_type in ("health_data", "emotion_diary"):
        consent = client.post(
            "/api/v1/consents",
            headers=headers,
            json={"consent_type": consent_type, "source": "test_setup"},
        )
        assert consent.status_code == 201, consent.text
    return headers, cast(str, signup.json()["id"])


def risk_result() -> BurnoutRiskEvaluationResponse:
    return BurnoutRiskEvaluationResponse.model_validate(
        {
            "score": 0,
            "level": "low",
            "is_provisional": False,
            "baseline_status": "ready",
            "data_quality": "sufficient",
            "category_scores": {},
            "factors": [],
            "summary": {
                "top_factor_codes": [],
                "available_signal_count": 7,
                "missing_signal_count": 0,
                "available_category_count": 5,
                "missing_category_count": 0,
            },
            "engine_version": "burnout-risk-rules-v1",
        }
    )


def evaluation_row(
    *,
    user_id: str,
    evaluation_id: str | None = None,
    record_date: date = date(2026, 7, 20),
    evaluated_at: datetime = datetime(2026, 7, 20, 12, tzinfo=UTC),
    daily_record_id: str | None = None,
    emotion_analysis_id: str | None = None,
    baseline_id: str | None = "baseline-id",
) -> BurnoutRiskEvaluation:
    result = risk_result()
    payload = result.model_dump(mode="json")
    return BurnoutRiskEvaluation(
        id=evaluation_id or str(uuid.uuid4()),
        user_id=user_id,
        record_date=record_date,
        evaluated_at=evaluated_at,
        daily_record_id=daily_record_id or str(uuid.uuid4()),
        emotion_analysis_result_id=emotion_analysis_id,
        baseline_id=baseline_id,
        engine_version=result.engine_version,
        score=result.score,
        level=result.level.value,
        is_provisional=result.is_provisional,
        baseline_status=result.baseline_status.value,
        data_quality=result.data_quality.value,
        category_scores=payload["category_scores"],
        factors=payload["factors"],
        summary=payload["summary"],
        created_at=evaluated_at,
    )


def seed_evaluation(
    engine: Engine,
    *,
    user_id: str,
    record_date: date,
    evaluated_at: datetime,
    evaluation_id: str | None = None,
) -> str:
    with Session(engine) as session:
        daily_record = session.scalar(
            select(BehavioralDailyRecord).where(
                BehavioralDailyRecord.user_id == user_id,
                BehavioralDailyRecord.record_date == record_date,
            )
        )
        if daily_record is None:
            daily_record = BehavioralDailyRecord(
                id=str(uuid.uuid4()),
                user_id=user_id,
                record_date=record_date,
                timezone="UTC",
                source_by_field={},
                coverage_by_field={},
            )
            session.add(daily_record)
            session.flush()
        evaluation = evaluation_row(
            user_id=user_id,
            evaluation_id=evaluation_id,
            record_date=record_date,
            evaluated_at=evaluated_at,
            daily_record_id=daily_record.id,
            baseline_id=None,
        )
        session.add(evaluation)
        session.commit()
        return evaluation.id


def seed_orchestration_inputs(
    engine: Engine,
    *,
    user_id: str,
    record_date: date,
    time_zone: str = "Asia/Seoul",
    include_emotion: bool = True,
) -> tuple[str, str, list[str]]:
    metadata_fields = (
        "sleep_minutes",
        "bedtime",
        "wake_time",
        "steps",
        "active_minutes",
        "exercise_minutes",
        "work_or_study_minutes",
        "rest_minutes",
        "schedule_count",
        "subjective_fatigue",
    )
    with Session(engine) as session:
        daily_record = BehavioralDailyRecord(
            user_id=user_id,
            record_date=record_date,
            sleep_minutes=420,
            bedtime=time(23, 30),
            wake_time=time(6, 30),
            steps=7000,
            active_minutes=50,
            study_work_minutes=480,
            rest_minutes=60,
            exercise_minutes=30,
            schedule_count=5,
            subjective_stress=4,
            subjective_fatigue=6,
            timezone=time_zone,
            source_by_field={
                field: "manual" for field in metadata_fields
            },
            coverage_by_field={
                field: "complete" for field in metadata_fields
            },
        )
        baseline = BehavioralBaseline(
            user_id=user_id,
            window_start=record_date - timedelta(days=7),
            window_end=record_date - timedelta(days=1),
            sample_days=7,
            sleep_minutes=450,
            study_work_minutes=420,
            rest_minutes=90,
            exercise_minutes=35,
            schedule_count=4,
            subjective_stress=3,
            subjective_fatigue=4,
            negative_emotion_probability=0.2,
            status=PersistenceBaselineStatus.READY,
            algorithm_version="behavioral-baseline-v1",
        )
        session.add_all([daily_record, baseline])
        session.flush()

        emotion_ids: list[str] = []
        if include_emotion:
            probabilities = {
                label.value: (
                    0.5
                    if label is EmotionLabel.JOY
                    else 0.1
                )
                for label in EmotionLabel
            }
            for index in range(2):
                emotion = EmotionAnalysisResult(
                    user_id=user_id,
                    record_date=record_date,
                    analyzed_at=datetime(
                        2026,
                        7,
                        20,
                        10 + index,
                        tzinfo=UTC,
                    ),
                    model_version=f"emotion-v{index + 1}",
                    predicted_emotion=EmotionLabel.JOY.value,
                    emotion=EmotionLabel.JOY.value,
                    confidence=0.8,
                    is_uncertain=False,
                    probabilities=probabilities,
                )
                session.add(emotion)
                session.flush()
                emotion_ids.append(emotion.id)
        session.commit()
        return daily_record.id, baseline.id, emotion_ids


def evaluation_count(engine: Engine, *, user_id: str) -> int:
    with Session(engine) as session:
        return cast(
            int,
            session.scalar(
                select(func.count(BurnoutRiskEvaluation.id)).where(
                    BurnoutRiskEvaluation.user_id == user_id
                )
            ),
        )


def _exception(exception_type: type[Exception]) -> Exception:
    exception = exception_type.__new__(exception_type)
    Exception.__init__(exception, "test failure")
    return exception


def test_create_requires_authentication_and_strict_date_body(
    client: TestClient,
) -> None:
    assert client.post(BASE_PATH, json={"date": "2026-07-20"}).status_code == 401
    headers, _ = authenticated_user(client)

    for payload in (
        {},
        {"date": "not-a-date"},
        {"date": 0},
        {"date": "2026-07-20T00:00:00"},
        {"date": "2026-07-20", "user_id": "another-user"},
        {"date": "2026-07-20", "unexpected": True},
    ):
        response = client.post(BASE_PATH, headers=headers, json=payload)
        assert response.status_code == 422


def test_create_rolls_back_reads_before_engine_and_returns_shared_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, user_id = authenticated_user(client)
    captured: dict[str, object] = {}
    prepared_snapshot = object()
    stored = evaluation_row(user_id=user_id)

    def prepare(
        session: Session,
        *,
        user_id: str,
        record_date: date,
    ) -> object:
        captured["session"] = session
        assert record_date == date(2026, 7, 20)
        assert session.in_transaction()
        return prepared_snapshot

    def evaluate(value: object) -> BurnoutRiskEvaluationResponse:
        assert value is prepared_snapshot
        session = cast(Session, captured["session"])
        assert not session.in_transaction()
        captured["evaluated"] = True
        return risk_result()

    def store(
        session: Session,
        *,
        prepared: object,
        result: BurnoutRiskEvaluationResponse,
    ) -> BurnoutRiskEvaluation:
        assert prepared is prepared_snapshot
        assert result == risk_result()
        assert not session.in_transaction()
        return stored

    monkeypatch.setattr(api_module, "prepare_risk_evaluation", prepare)
    monkeypatch.setattr(api_module, "evaluate_prepared_risk", evaluate)
    monkeypatch.setattr(api_module, "store_prepared_risk_evaluation", store)

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == stored.id
    assert body["user_id"] == user_id
    assert body["date"] == "2026-07-20"
    assert body["daily_record_id"] == stored.daily_record_id
    assert body["emotion_analysis_id"] is None
    assert body["baseline_id"] == stored.baseline_id
    assert captured["evaluated"] is True
    schema = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(body["result"])


@pytest.mark.parametrize(
    ("error_type", "expected_status", "expected_detail"),
    [
        (
            DailyRecordNotFoundError,
            404,
            "Behavioral record not found.",
        ),
        (
            FutureEvaluationDateError,
            422,
            "date cannot be in the future for the record timezone.",
        ),
        (
            ReadyBaselineNotFoundError,
            409,
            "A ready baseline before the evaluation date is required.",
        ),
        (
            RiskInputUnavailableError,
            503,
            "Risk evaluation input metadata is unavailable.",
        ),
    ],
)
def test_create_maps_input_policy_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
    expected_status: int,
    expected_detail: str,
) -> None:
    headers, _ = authenticated_user(
        client,
        email=f"{expected_status}-{error_type.__name__}@example.com",
    )

    def fail_prepare(*args: object, **kwargs: object) -> None:
        raise _exception(error_type)

    monkeypatch.setattr(
        api_module,
        "prepare_risk_evaluation",
        fail_prepare,
    )
    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}


def test_create_maps_changed_inputs_to_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = authenticated_user(client)
    monkeypatch.setattr(
        api_module,
        "prepare_risk_evaluation",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        api_module,
        "evaluate_prepared_risk",
        lambda prepared: risk_result(),
    )

    def fail_store(*args: object, **kwargs: object) -> None:
        raise _exception(RiskInputsChangedError)

    monkeypatch.setattr(
        api_module,
        "store_prepared_risk_evaluation",
        fail_store,
    )

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Risk evaluation inputs changed; retry the evaluation."
    }


@pytest.mark.parametrize(
    ("failure_stage", "expected_detail"),
    [
        ("load", "Risk evaluation inputs could not be loaded."),
        ("calculate", "Risk evaluation could not be calculated."),
        ("save", "Risk evaluation could not be saved."),
    ],
)
def test_create_hides_unexpected_operation_failures(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    expected_detail: str,
) -> None:
    headers, _ = authenticated_user(
        client,
        email=f"private-{failure_stage}@example.com",
    )

    def private_failure(*args: object, **kwargs: object) -> None:
        raise RuntimeError("private implementation detail")

    monkeypatch.setattr(
        api_module,
        "prepare_risk_evaluation",
        (
            private_failure
            if failure_stage == "load"
            else lambda *args, **kwargs: object()
        ),
    )
    monkeypatch.setattr(
        api_module,
        "evaluate_prepared_risk",
        (
            private_failure
            if failure_stage == "calculate"
            else lambda prepared: risk_result()
        ),
    )
    monkeypatch.setattr(
        api_module,
        "store_prepared_risk_evaluation",
        (
            private_failure
            if failure_stage == "save"
            else lambda *args, **kwargs: evaluation_row(
                user_id="unused"
            )
        ),
    )

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": expected_detail}
    assert "private" not in response.text


def test_repeat_create_is_not_suppressed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, user_id = authenticated_user(client)
    created_ids: list[str] = []
    monkeypatch.setattr(
        api_module,
        "prepare_risk_evaluation",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        api_module,
        "evaluate_prepared_risk",
        lambda prepared: risk_result(),
    )

    def store(*args: object, **kwargs: object) -> BurnoutRiskEvaluation:
        row = evaluation_row(user_id=user_id)
        created_ids.append(row.id)
        return row

    monkeypatch.setattr(api_module, "store_prepared_risk_evaluation", store)

    responses = [
        client.post(
            BASE_PATH,
            headers=headers,
            json={"date": "2026-07-20"},
        )
        for _ in range(2)
    ]

    assert [response.status_code for response in responses] == [201, 201]
    assert len(set(created_ids)) == 2
    assert [response.json()["id"] for response in responses] == created_ids


def test_real_orchestration_appends_and_selects_latest_provenance(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    daily_id, prior_baseline_id, emotion_ids = seed_orchestration_inputs(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 20),
    )
    with Session(migrated_engine) as session:
        same_day_baseline = BehavioralBaseline(
            user_id=user_id,
            window_start=date(2026, 7, 14),
            window_end=date(2026, 7, 20),
            sample_days=7,
            sleep_minutes=450,
            status=PersistenceBaselineStatus.READY,
            algorithm_version="must-not-be-selected",
        )
        session.add(same_day_baseline)
        session.commit()

    responses = [
        client.post(
            BASE_PATH,
            headers=headers,
            json={"date": "2026-07-20"},
        )
        for _ in range(2)
    ]
    latest = client.get(f"{BASE_PATH}/latest", headers=headers)
    history = client.get(BASE_PATH, headers=headers)

    assert [response.status_code for response in responses] == [201, 201]
    first, second = [response.json() for response in responses]
    assert first["id"] != second["id"]
    assert second["daily_record_id"] == daily_id
    assert second["emotion_analysis_id"] == emotion_ids[-1]
    assert second["baseline_id"] == prior_baseline_id
    assert second["date"] == "2026-07-20"
    assert latest.status_code == 200
    assert latest.json()["id"] == second["id"]
    assert [row["id"] for row in history.json()] == [
        second["id"],
        first["id"],
    ]
    assert evaluation_count(migrated_engine, user_id=user_id) == 2


def test_real_orchestration_allows_missing_emotion(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    _, baseline_id, emotion_ids = seed_orchestration_inputs(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 19),
        include_emotion=False,
    )

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-19"},
    )

    assert response.status_code == 201
    assert response.json()["emotion_analysis_id"] is None
    assert response.json()["baseline_id"] == baseline_id
    assert emotion_ids == []
    assert evaluation_count(migrated_engine, user_id=user_id) == 1


def test_daily_emotion_baseline_and_risk_apis_form_user_scoped_flow(
    client: TestClient,
) -> None:
    headers, user_id = authenticated_user(client)
    for day in range(13, 21):
        daily_response = client.post(
            "/api/v1/behavioral-records",
            headers=headers,
            json=canonical_daily_record_payload(
                record_date=f"2026-07-{day:02d}"
            ),
        )
        assert daily_response.status_code == 201, daily_response.text

    application = cast(FastAPI, client.app)
    application.dependency_overrides[get_ai_service_client] = lambda: cast(
        AIServiceClient,
        FakeAIServiceClient(),
    )
    try:
        emotion = client.post(
            "/api/v1/emotion-analyses",
            headers=headers,
            json={
                "record_date": "2026-07-20",
                "hs01": "first answer",
                "hs02": "second answer",
            },
        )
    finally:
        application.dependency_overrides.pop(get_ai_service_client, None)
    assert emotion.status_code == 201, emotion.text

    baseline = client.post(
        "/api/v1/baselines",
        headers=headers,
        json={"as_of_date": "2026-07-19"},
    )
    assert baseline.status_code == 201, baseline.text
    assert baseline.json()["status"] == "ready"

    created = [
        client.post(
            BASE_PATH,
            headers=headers,
            json={"date": "2026-07-20"},
        )
        for _ in range(2)
    ]
    assert [response.status_code for response in created] == [201, 201]
    first, second = [response.json() for response in created]
    assert second["user_id"] == user_id
    assert second["date"] == "2026-07-20"
    assert second["emotion_analysis_id"] == emotion.json()["id"]
    assert second["baseline_id"] == baseline.json()["id"]
    assert first["id"] != second["id"]

    latest = client.get(f"{BASE_PATH}/latest", headers=headers)
    history = client.get(BASE_PATH, headers=headers)
    assert latest.json()["id"] == second["id"]
    assert [row["id"] for row in history.json()] == [
        second["id"],
        first["id"],
    ]

    other_headers, _ = authenticated_user(
        client,
        email="risk-api-other-user@example.com",
    )
    assert (
        client.get(f"{BASE_PATH}/latest", headers=other_headers).status_code
        == 404
    )
    assert client.get(BASE_PATH, headers=other_headers).json() == []


def test_neutral_gate_result_keeps_provenance_but_risk_uses_behavior_only(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = authenticated_user(
        client,
        email="risk-api-abstention@example.com",
    )
    for day in range(13, 21):
        response = client.post(
            "/api/v1/behavioral-records",
            headers=headers,
            json=canonical_daily_record_payload(
                record_date=f"2026-07-{day:02d}"
            ),
        )
        assert response.status_code == 201, response.text

    application = cast(FastAPI, client.app)
    application.dependency_overrides[get_ai_service_client] = lambda: cast(
        AIServiceClient,
        NeutralGateAIServiceClient(),
    )
    try:
        emotion = client.post(
            "/api/v1/emotion-analyses",
            headers=headers,
            json={
                "record_date": "2026-07-20",
                "hs01": "오늘은 그냥 평범했다",
                "hs02": "특별한 일은 없었다",
            },
        )
    finally:
        application.dependency_overrides.pop(get_ai_service_client, None)

    assert emotion.status_code == 201, emotion.text
    assert emotion.json()["emotion"] is None
    assert emotion.json()["provisional"] is True
    assert emotion.json()["neutral_gate_decision"] == "neutral"

    baseline = client.post(
        "/api/v1/baselines",
        headers=headers,
        json={"as_of_date": "2026-07-19"},
    )
    assert baseline.status_code == 201, baseline.text

    captured: dict[str, BurnoutRiskEvaluationRequest] = {}
    real_evaluate = api_module.evaluate_prepared_risk

    def capture_request(
        prepared: PreparedRiskEvaluation,
    ) -> BurnoutRiskEvaluationResponse:
        captured["request"] = prepared.request
        return real_evaluate(prepared)

    monkeypatch.setattr(
        api_module,
        "evaluate_prepared_risk",
        capture_request,
    )

    risk = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert risk.status_code == 201, risk.text
    assert risk.json()["emotion_analysis_id"] == emotion.json()["id"]
    current = captured["request"].current
    assert current.emotion_probabilities is None
    assert current.emotion_confidence is None
    assert current.emotion_uncertain is None


def test_real_engine_failure_leaves_no_evaluation(
    client: TestClient,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, user_id = authenticated_user(client)
    seed_orchestration_inputs(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 20),
    )

    def fail_engine(
        engine: BurnoutRiskEngine,
        request: BurnoutRiskEvaluationRequest,
    ) -> BurnoutRiskEvaluationResponse:
        del engine, request
        raise RuntimeError("private engine detail")

    monkeypatch.setattr(BurnoutRiskEngine, "evaluate", fail_engine)

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Risk evaluation could not be calculated."
    }
    assert "private" not in response.text
    assert evaluation_count(migrated_engine, user_id=user_id) == 0


def test_real_provenance_deletion_returns_conflict_without_evaluation(
    client: TestClient,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, user_id = authenticated_user(client)
    seed_orchestration_inputs(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 20),
    )
    original_evaluate = api_module.evaluate_prepared_risk

    def evaluate_then_delete(
        prepared: PreparedRiskEvaluation,
    ) -> BurnoutRiskEvaluationResponse:
        result = original_evaluate(prepared)
        with Session(migrated_engine) as session:
            baseline = session.get(
                BehavioralBaseline,
                prepared.baseline_id,
            )
            assert baseline is not None
            session.delete(baseline)
            session.commit()
        return result

    monkeypatch.setattr(
        api_module,
        "evaluate_prepared_risk",
        evaluate_then_delete,
    )

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Risk evaluation inputs changed; retry the evaluation."
    }
    assert evaluation_count(migrated_engine, user_id=user_id) == 0


def test_real_prepare_uses_daily_record_timezone_for_future_boundary(
    client: TestClient,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, user_id = authenticated_user(client)
    seed_orchestration_inputs(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 27),
        time_zone="Pacific/Honolulu",
        include_emotion=False,
    )
    observed: dict[str, str] = {}

    def local_today(*, time_zone: str, now: datetime | None) -> date:
        del now
        observed["time_zone"] = time_zone
        return date(2026, 7, 26)

    monkeypatch.setattr(service_module, "_local_today", local_today)

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-27"},
    )

    assert response.status_code == 422
    assert observed == {"time_zone": "Pacific/Honolulu"}
    assert evaluation_count(migrated_engine, user_id=user_id) == 0


def test_invalid_daily_metadata_takes_precedence_over_future_check(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    with Session(migrated_engine) as session:
        session.add(
            BehavioralDailyRecord(
                user_id=user_id,
                record_date=date(2099, 1, 1),
                timezone="Pacific/Honolulu",
                source_by_field=None,
                coverage_by_field=None,
            )
        )
        session.commit()

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2099-01-01"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Risk evaluation input metadata is unavailable."
    }
    assert evaluation_count(migrated_engine, user_id=user_id) == 0


def test_commit_failure_rolls_back_real_evaluation(
    client: TestClient,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, user_id = authenticated_user(client)
    seed_orchestration_inputs(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 20),
    )

    def fail_commit(session: Session) -> None:
        del session
        raise RuntimeError("private commit detail")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Risk evaluation could not be saved."
    }
    assert "private" not in response.text
    assert evaluation_count(migrated_engine, user_id=user_id) == 0


def test_latest_and_history_are_dated_user_scoped_and_stably_ordered(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    _, other_user_id = authenticated_user(
        client,
        email="other-risk-history@example.com",
    )
    timestamp = datetime(2026, 7, 20, 12, tzinfo=UTC)
    lower_id = "00000000-0000-0000-0000-000000000001"
    higher_id = "00000000-0000-0000-0000-000000000002"
    first_id = seed_evaluation(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 19),
        evaluated_at=timestamp - timedelta(hours=1),
    )
    seed_evaluation(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 20),
        evaluated_at=timestamp,
        evaluation_id=lower_id,
    )
    seed_evaluation(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 20),
        evaluated_at=timestamp,
        evaluation_id=higher_id,
    )
    seed_evaluation(
        migrated_engine,
        user_id=other_user_id,
        record_date=date(2026, 7, 21),
        evaluated_at=timestamp + timedelta(days=1),
    )

    latest = client.get(f"{BASE_PATH}/latest", headers=headers)
    history = client.get(BASE_PATH, headers=headers)

    assert latest.status_code == 200
    assert latest.json()["id"] == higher_id
    assert [row["id"] for row in history.json()] == [
        higher_id,
        lower_id,
        first_id,
    ]
    assert {row["user_id"] for row in history.json()} == {user_id}


def test_history_filters_are_independently_inclusive_and_paginated(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    start = datetime(2026, 7, 1, tzinfo=UTC)
    ids = [
        seed_evaluation(
            migrated_engine,
            user_id=user_id,
            record_date=date(2026, 7, 1) + timedelta(days=index),
            evaluated_at=start + timedelta(minutes=index),
        )
        for index in range(21)
    ]

    default_page = client.get(BASE_PATH, headers=headers)
    from_only = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_from": "2026-07-20"},
    )
    to_only = client.get(
        BASE_PATH,
        headers=headers,
        params={"date_to": "2026-07-02"},
    )
    bounded = client.get(
        BASE_PATH,
        headers=headers,
        params={
            "date_from": "2026-07-02",
            "date_to": "2026-07-20",
            "limit": 1,
            "offset": 1,
        },
    )
    empty = client.get(
        BASE_PATH,
        headers=headers,
        params={"offset": 21},
    )

    assert len(default_page.json()) == 20
    assert [row["id"] for row in from_only.json()] == [ids[20], ids[19]]
    assert [row["id"] for row in to_only.json()] == [ids[1], ids[0]]
    assert [row["id"] for row in bounded.json()] == [ids[18]]
    assert empty.json() == []


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-07-20", "date_to": "2026-07-19"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_history_rejects_invalid_ranges_and_pagination(
    client: TestClient,
    params: dict[str, str | int],
) -> None:
    headers, _ = authenticated_user(
        client,
        email=f"invalid-risk-{uuid.uuid4()}@example.com",
    )

    response = client.get(BASE_PATH, headers=headers, params=params)

    assert response.status_code == 422


def test_latest_missing_returns_not_found(client: TestClient) -> None:
    headers, _ = authenticated_user(client)

    response = client.get(f"{BASE_PATH}/latest", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Risk evaluation not found."}


def test_deleted_daily_provenance_is_omitted_from_public_reads(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(client)
    evaluation_id = seed_evaluation(
        migrated_engine,
        user_id=user_id,
        record_date=date(2026, 7, 20),
        evaluated_at=datetime(2026, 7, 20, 12, tzinfo=UTC),
    )
    with Session(migrated_engine) as session:
        evaluation = session.get(BurnoutRiskEvaluation, evaluation_id)
        assert evaluation is not None
        daily_record = session.get(
            BehavioralDailyRecord,
            evaluation.daily_record_id,
        )
        assert daily_record is not None
        session.delete(daily_record)
        session.commit()
    with Session(migrated_engine) as session:
        evaluation = session.get(BurnoutRiskEvaluation, evaluation_id)
        assert evaluation is not None
        assert evaluation.daily_record_id is None

    latest = client.get(f"{BASE_PATH}/latest", headers=headers)
    history = client.get(BASE_PATH, headers=headers)

    assert latest.status_code == 404
    assert latest.json() == {"detail": "Risk evaluation not found."}
    assert history.status_code == 200
    assert history.json() == []


def test_other_users_daily_record_is_indistinguishable_from_missing(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client)
    other_headers, _ = authenticated_user(
        client,
        email="other-daily-owner@example.com",
    )
    created = client.post(
        "/api/v1/behavioral-records",
        headers=other_headers,
        json=canonical_daily_record_payload(record_date="2026-07-20"),
    )
    assert created.status_code == 201

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Behavioral record not found."}


def test_valid_daily_without_eligible_baseline_returns_conflict(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client)
    created = client.post(
        "/api/v1/behavioral-records",
        headers=headers,
        json=canonical_daily_record_payload(record_date="2026-07-20"),
    )
    assert created.status_code == 201

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"date": "2026-07-20"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "A ready baseline before the evaluation date is required."
    }


def test_openapi_declares_strict_authenticated_contract(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    collection = schema["paths"][BASE_PATH]
    latest = schema["paths"][f"{BASE_PATH}/latest"]["get"]
    create = collection["post"]
    history = collection["get"]
    create_schema = schema["components"]["schemas"]["RiskEvaluationCreate"]
    response_schema = schema["components"]["schemas"][
        "RiskEvaluationResponse"
    ]
    history_parameters = {
        parameter["name"]: parameter for parameter in history["parameters"]
    }

    assert create["security"]
    assert history["security"]
    assert latest["security"]
    assert "201" in create["responses"]
    assert create_schema["required"] == ["date"]
    assert create_schema["additionalProperties"] is False
    assert set(create_schema["properties"]) == {"date"}
    assert {
        "id",
        "user_id",
        "date",
        "evaluated_at",
        "daily_record_id",
        "emotion_analysis_id",
        "baseline_id",
        "created_at",
        "result",
    } == set(response_schema["properties"])
    assert history_parameters["limit"]["schema"]["default"] == 20
    assert history_parameters["limit"]["schema"]["minimum"] == 1
    assert history_parameters["limit"]["schema"]["maximum"] == 100
    assert history_parameters["offset"]["schema"]["default"] == 0
    assert history_parameters["offset"]["schema"]["minimum"] == 0
