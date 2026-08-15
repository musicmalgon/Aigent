from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.baselines import MINIMUM_SAMPLE_DAYS
from tests.api.test_recovery_reports import (
    SuccessfulReportClient,
    use_report_client,
)
from tests.daily_record_contract import canonical_daily_record_payload

DASHBOARD_PATH = "/api/v1/dashboard"
READINESS_PATH = "/api/v1/readiness"
BEHAVIORAL_PATH = "/api/v1/behavioral-records"
BASELINE_PATH = "/api/v1/baselines"
RISK_PATH = "/api/v1/risk-evaluations"
REPORT_PATH = "/api/v1/recovery-reports"
PASSWORD = "correct-horse-battery-staple1!"
BASELINE_WINDOW_END = "2026-07-19"
EVALUATION_DATE = "2026-07-20"
EMPTY_RECORD_STATUS = {"today_recorded": False, "recorded_days": 0}


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
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    # 대시보드 테스트는 생활기록 쓰기 API로 상태를 쌓아 올린다. 쓰기는
    # 동의 게이트가 걸려 있으므로 헬퍼에서 미리 부여해 둔다.
    for consent_type in ("health_data", "emotion_diary"):
        consent = client.post(
            "/api/v1/consents",
            headers=headers,
            json={"consent_type": consent_type, "source": "test_setup"},
        )
        assert consent.status_code == 201, consent.text
    return headers, cast(str, signup.json()["id"])


def post_daily_record(
    client: TestClient,
    headers: dict[str, str],
    *,
    record_date: str,
    **overrides: object,
) -> None:
    response = client.post(
        BEHAVIORAL_PATH,
        headers=headers,
        json=canonical_daily_record_payload(
            record_date=record_date,
            **overrides,
        ),
    )
    assert response.status_code == 201, response.text


def seed_baseline_window(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    for day in range(13, 20):
        post_daily_record(client, headers, record_date=f"2026-07-{day:02d}")


def seed_risk_evaluation(
    client: TestClient,
    headers: dict[str, str],
) -> dict[str, Any]:
    seed_baseline_window(client, headers)
    # 평가일 기록만 평소 기준보다 나쁘게 넣어야 위험 요인이 여러 개 나온다.
    post_daily_record(
        client,
        headers,
        record_date=EVALUATION_DATE,
        sleep_minutes=300,
        work_or_study_minutes=600,
        rest_minutes=20,
        exercise_minutes=10,
        schedule_count=8,
        subjective_fatigue=9.0,
    )
    baseline = client.post(
        BASELINE_PATH,
        headers=headers,
        json={"as_of_date": BASELINE_WINDOW_END},
    )
    assert baseline.status_code == 201, baseline.text
    assert baseline.json()["status"] == "ready"

    evaluation = client.post(
        RISK_PATH,
        headers=headers,
        json={"date": EVALUATION_DATE},
    )
    assert evaluation.status_code == 201, evaluation.text
    return cast(dict[str, Any], evaluation.json())


def readiness_state(client: TestClient, headers: dict[str, str]) -> str:
    response = client.get(READINESS_PATH, headers=headers)
    assert response.status_code == 200, response.text
    return cast(str, response.json()["state"])


def dashboard_body(
    client: TestClient,
    headers: dict[str, str],
) -> dict[str, Any]:
    response = client.get(DASHBOARD_PATH, headers=headers)
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_dashboard_reports_absent_sources_for_a_fresh_user(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(
        client,
        email="dashboard-fresh@example.com",
    )

    assert dashboard_body(client, headers) == {
        "record_status": EMPTY_RECORD_STATUS,
        "baseline": None,
        "latest_risk": None,
        "latest_report": None,
    }
    assert readiness_state(client, headers) == "insufficient_records"


def test_readiness_turns_pending_at_the_minimum_record_count(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(
        client,
        email="dashboard-pending@example.com",
    )
    today = datetime.now(UTC).date()

    for offset in reversed(range(1, MINIMUM_SAMPLE_DAYS)):
        post_daily_record(
            client,
            headers,
            record_date=(today - timedelta(days=offset)).isoformat(),
        )
    assert readiness_state(client, headers) == "insufficient_records"

    post_daily_record(client, headers, record_date=today.isoformat())

    assert dashboard_body(client, headers)["record_status"] == {
        "today_recorded": True,
        "recorded_days": MINIMUM_SAMPLE_DAYS,
    }
    assert dashboard_body(client, headers)["baseline"] is None
    assert readiness_state(client, headers) == "baseline_pending"


def test_dashboard_reports_a_ready_baseline(client: TestClient) -> None:
    headers, _ = authenticated_user(
        client,
        email="dashboard-baseline@example.com",
    )
    seed_baseline_window(client, headers)

    baseline = client.post(
        BASELINE_PATH,
        headers=headers,
        json={"as_of_date": BASELINE_WINDOW_END},
    )
    assert baseline.status_code == 201, baseline.text

    body = dashboard_body(client, headers)
    assert body["record_status"] == {
        "today_recorded": False,
        "recorded_days": MINIMUM_SAMPLE_DAYS,
    }
    assert body["baseline"] == {
        "status": "ready",
        "sample_days": MINIMUM_SAMPLE_DAYS,
        "window_end": BASELINE_WINDOW_END,
        "created_at": baseline.json()["created_at"],
    }
    assert body["latest_risk"] is None
    assert body["latest_report"] is None
    assert readiness_state(client, headers) == "baseline_ready"


def test_dashboard_reports_the_top_three_risk_factors(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(
        client,
        email="dashboard-risk@example.com",
    )
    evaluation = seed_risk_evaluation(client, headers)

    factors = evaluation["result"]["factors"]
    contributions = [factor["contribution"] for factor in factors]
    # 3개보다 많아야 "상위 3개만 노출"이 실제로 검증된다.
    assert len(factors) > 3
    assert contributions == sorted(contributions, reverse=True)

    body = dashboard_body(client, headers)
    assert body["latest_risk"] == {
        "level": evaluation["result"]["level"],
        "date": EVALUATION_DATE,
        "top_factors": [factor["code"] for factor in factors[:3]],
    }
    assert body["baseline"] is not None
    assert body["latest_report"] is None
    assert readiness_state(client, headers) == "risk_evaluation_ready"


def test_dashboard_reports_the_latest_recovery_report(
    client: TestClient,
    test_app: FastAPI,
) -> None:
    headers, _ = authenticated_user(
        client,
        email="dashboard-report@example.com",
    )
    evaluation = seed_risk_evaluation(client, headers)
    use_report_client(test_app, SuccessfulReportClient())

    report = client.post(
        REPORT_PATH,
        headers=headers,
        json={"risk_evaluation_id": evaluation["id"]},
    )
    assert report.status_code == 201, report.text

    body = dashboard_body(client, headers)
    assert body["latest_report"] == {
        "id": report.json()["id"],
        "headline": report.json()["content"]["headline"],
        "generation_status": "llm_generated",
        "generated_at": report.json()["generated_at"],
    }
    assert body["latest_risk"] is not None
    assert readiness_state(client, headers) == "recovery_report_ready"


def test_dashboard_and_readiness_require_authentication(
    client: TestClient,
) -> None:
    assert client.get(DASHBOARD_PATH).status_code == 401
    assert client.get(READINESS_PATH).status_code == 401


def test_dashboard_never_reflects_another_users_data(
    client: TestClient,
    test_app: FastAPI,
) -> None:
    owner_headers, _ = authenticated_user(
        client,
        email="dashboard-owner@example.com",
    )
    other_headers, _ = authenticated_user(
        client,
        email="dashboard-other@example.com",
    )
    evaluation = seed_risk_evaluation(client, owner_headers)
    use_report_client(test_app, SuccessfulReportClient())
    report = client.post(
        REPORT_PATH,
        headers=owner_headers,
        json={"risk_evaluation_id": evaluation["id"]},
    )
    assert report.status_code == 201, report.text

    assert dashboard_body(client, other_headers) == {
        "record_status": EMPTY_RECORD_STATUS,
        "baseline": None,
        "latest_risk": None,
        "latest_report": None,
    }
    assert readiness_state(client, other_headers) == "insufficient_records"

    owner_body = dashboard_body(client, owner_headers)
    assert owner_body["latest_report"]["id"] == report.json()["id"]
    assert readiness_state(client, owner_headers) == "recovery_report_ready"
