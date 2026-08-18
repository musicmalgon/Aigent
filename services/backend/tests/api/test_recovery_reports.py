from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_ai_service_client
from app.clients.ai import AIServiceConnectionError
from app.domain.recovery.models import (
    RecoveryChangedItem,
    RecoveryRecommendationDescription,
    RecoveryReportGenerationRequest,
    RecoveryReportGenerationResponse,
)
from app.domain.risk.models import BurnoutRiskEvaluationResponse
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    PersistenceBaselineStatus,
    RecoveryReport,
)
from tests.persistence.helpers import daily_record

BASE_PATH = "/api/v1/recovery-reports"
PASSWORD = "correct-horse-battery-staple"
REPORT_DATE = date(2026, 7, 20)


def authenticated_user(
    client: TestClient,
    *,
    email: str,
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
    return (
        {"Authorization": f"Bearer {login.json()['access_token']}"},
        cast(str, signup.json()["id"]),
    )


def risk_result() -> BurnoutRiskEvaluationResponse:
    return BurnoutRiskEvaluationResponse.model_validate(
        {
            "score": 30,
            "level": "moderate",
            "is_provisional": False,
            "baseline_status": "ready",
            "data_quality": "sufficient",
            "category_scores": {"sleep": 20, "recovery": 10},
            "factors": [
                {
                    "code": "sleep_decrease",
                    "category": "sleep",
                    "kind": "risk",
                    "severity": 0.8,
                    "weight": 0.5,
                    "contribution": 20,
                    "observed_value": 300,
                    "baseline_value": 420,
                    "change_percent": -28.57,
                    "message_key": "risk.sleep_decrease",
                },
                {
                    "code": "rest_decrease",
                    "category": "recovery",
                    "kind": "risk",
                    "severity": 0.5,
                    "weight": 0.4,
                    "contribution": 10,
                    "observed_value": 30,
                    "baseline_value": 90,
                    "change_percent": -66.67,
                    "message_key": "risk.rest_decrease",
                },
            ],
            "summary": {
                "top_factor_codes": [
                    "sleep_decrease",
                    "rest_decrease",
                ],
                "available_signal_count": 7,
                "missing_signal_count": 0,
                "available_category_count": 5,
                "missing_category_count": 0,
            },
            "engine_version": "burnout-risk-rules-v1",
        }
    )


def seed_report_inputs(engine: Engine, *, user_id: str) -> str:
    with Session(engine) as session:
        records = [
            daily_record(
                session,
                user_id=user_id,
                record_date=REPORT_DATE - timedelta(days=offset),
                sleep_minutes=300,
                rest_minutes=30,
            )
            for offset in range(7)
        ]
        target = next(
            record for record in records if record.record_date == REPORT_DATE
        )
        baseline = BehavioralBaseline(
            user_id=user_id,
            window_start=REPORT_DATE - timedelta(days=13),
            window_end=REPORT_DATE - timedelta(days=7),
            sample_days=7,
            sleep_minutes=420,
            study_work_minutes=420,
            rest_minutes=90,
            exercise_minutes=30,
            schedule_count=4,
            subjective_stress=4,
            subjective_fatigue=5,
            negative_emotion_probability=0.2,
            status=PersistenceBaselineStatus.READY,
            algorithm_version="behavioral-baseline-v1",
        )
        session.add(baseline)
        session.flush()

        result = risk_result()
        payload = result.model_dump(mode="json")
        evaluation = BurnoutRiskEvaluation(
            user_id=user_id,
            record_date=REPORT_DATE,
            evaluated_at=datetime(2026, 7, 20, 12, tzinfo=UTC),
            daily_record_id=target.id,
            baseline_id=baseline.id,
            engine_version=result.engine_version,
            score=result.score,
            level=result.level.value,
            is_provisional=result.is_provisional,
            baseline_status=result.baseline_status.value,
            data_quality=result.data_quality.value,
            category_scores=payload["category_scores"],
            factors=payload["factors"],
            summary=payload["summary"],
        )
        session.add(evaluation)
        session.commit()
        return evaluation.id


class SuccessfulReportClient:
    async def generate_recovery_report(
        self,
        request: RecoveryReportGenerationRequest,
    ) -> RecoveryReportGenerationResponse:
        return RecoveryReportGenerationResponse(
            headline="수면과 휴식의 변화를 함께 살펴봤어요.",
            summary="제공된 기록에서 수면과 휴식 시간이 줄어든 흐름이 보여요.",
            weekly_observation="최근 7일 기록을 평소 기준과 비교했어요.",
            changed_items=[
                RecoveryChangedItem(
                    factor_code=change.factor_code,
                    title=f"{change.factor_code.value} 변화",
                    description=change.fact_text,
                )
                for change in request.changes
            ],
            recommendation_intro="부담이 적은 한 가지부터 시작해 보세요.",
            recommendation_descriptions=[
                RecoveryRecommendationDescription(
                    action_id=action.id,
                    reason="미리 선택된 행동을 가볍게 시도해 볼 수 있어요.",
                )
                for action in request.selected_actions
            ],
            model_name="gemini-test",
            prompt_version=request.prompt_version,
        )


class FailingReportClient:
    async def generate_recovery_report(
        self,
        request: RecoveryReportGenerationRequest,
    ) -> RecoveryReportGenerationResponse:
        del request
        raise AIServiceConnectionError(
            "synthetic downstream failure",
            endpoint="v1/recovery-reports/generate",
            error_code="downstream_connection_failure",
        )


def use_report_client(test_app: FastAPI, client: object) -> None:
    test_app.dependency_overrides[get_ai_service_client] = lambda: client


def report_count(engine: Engine, *, user_id: str) -> int:
    with Session(engine) as session:
        return cast(
            int,
            session.scalar(
                select(func.count(RecoveryReport.id)).where(
                    RecoveryReport.user_id == user_id
                )
            ),
        )


def test_recovery_report_end_to_end_and_append_only_fallback(
    client: TestClient,
    test_app: FastAPI,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(
        client,
        email="recovery-report@example.com",
    )
    evaluation_id = seed_report_inputs(migrated_engine, user_id=user_id)

    use_report_client(test_app, SuccessfulReportClient())
    generated = client.post(
        BASE_PATH,
        headers=headers,
        json={"risk_evaluation_id": evaluation_id},
    )

    assert generated.status_code == 201
    body = generated.json()
    assert body["generation_status"] == "llm_generated"
    assert body["model_name"] == "gemini-test"
    assert body["period_start"] == "2026-07-14"
    assert body["period_end"] == "2026-07-20"
    assert body["facts"]["period"]["record_days"] == 7
    assert body["facts"]["changes"][0]["recent_value"] == 300
    assert body["facts"]["changes"][0]["baseline_value"] == 420
    assert body["selected_actions"][0]["id"] == "SLEEP_EARLY_60"

    use_report_client(test_app, FailingReportClient())
    fallback = client.post(
        BASE_PATH,
        headers=headers,
        json={"risk_evaluation_id": evaluation_id},
    )

    assert fallback.status_code == 201
    assert fallback.json()["generation_status"] == "template_fallback"
    assert fallback.json()["model_name"] is None
    assert report_count(migrated_engine, user_id=user_id) == 2

    latest = client.get(f"{BASE_PATH}/latest", headers=headers)
    history = client.get(BASE_PATH, headers=headers)
    assert latest.status_code == 200
    assert latest.json()["id"] == fallback.json()["id"]
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [
        fallback.json()["id"],
        generated.json()["id"],
    ]
    assert client.get(
        f"{BASE_PATH}?date_from=2026-07-21",
        headers=headers,
    ).json() == []
    assert (
        client.get(
            f"{BASE_PATH}?date_from=2026-07-21&date_to=2026-07-20",
            headers=headers,
        ).status_code
        == 422
    )


def test_recovery_report_auth_strict_body_and_user_isolation(
    client: TestClient,
    test_app: FastAPI,
    migrated_engine: Engine,
) -> None:
    first_headers, first_user = authenticated_user(
        client,
        email="recovery-owner@example.com",
    )
    second_headers, _ = authenticated_user(
        client,
        email="recovery-other@example.com",
    )
    evaluation_id = seed_report_inputs(migrated_engine, user_id=first_user)
    use_report_client(test_app, SuccessfulReportClient())

    assert (
        client.post(
            BASE_PATH,
            json={"risk_evaluation_id": evaluation_id},
        ).status_code
        == 401
    )
    assert (
        client.post(
            BASE_PATH,
            headers=first_headers,
            json={
                "risk_evaluation_id": evaluation_id,
                "user_id": first_user,
            },
        ).status_code
        == 422
    )
    hidden = client.post(
        BASE_PATH,
        headers=second_headers,
        json={"risk_evaluation_id": evaluation_id},
    )
    assert hidden.status_code == 404
    assert report_count(migrated_engine, user_id=first_user) == 0


def test_legacy_daily_metadata_returns_503_without_guessing(
    client: TestClient,
    test_app: FastAPI,
    migrated_engine: Engine,
) -> None:
    headers, user_id = authenticated_user(
        client,
        email="recovery-legacy@example.com",
    )
    evaluation_id = seed_report_inputs(migrated_engine, user_id=user_id)
    with Session(migrated_engine) as session:
        target = session.scalar(
            select(BehavioralDailyRecord).where(
                BehavioralDailyRecord.user_id == user_id,
                BehavioralDailyRecord.record_date == REPORT_DATE,
            )
        )
        assert target is not None
        target.source_by_field = None
        target.coverage_by_field = None
        session.commit()
    use_report_client(test_app, SuccessfulReportClient())

    response = client.post(
        BASE_PATH,
        headers=headers,
        json={"risk_evaluation_id": evaluation_id},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Recovery report inputs are unavailable."
    }
    assert report_count(migrated_engine, user_id=user_id) == 0
