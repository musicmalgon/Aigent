"""가입부터 대시보드까지 실제 HTTP 호출만으로 잇는 전체 파이프라인 E2E.

엔드포인트별 테스트 파일은 각자 필요한 선행 데이터를 DB에 직접 시드하거나
좁은 구간만 호출한다. 그래서 개별 엔드포인트가 모두 통과하면서도 앞 단계의
"실제 응답"이 뒤 단계의 입력으로 이어지지 않는 회귀는 잡히지 않는다.
이 파일은 그 연결 고리만을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_ai_service_client
from app.clients.ai import AIServiceClient
from app.domain.risk.models import RiskLevel
from app.services.baselines import MINIMUM_SAMPLE_DAYS
from tests.api.test_recovery_reports import SuccessfulReportClient
from tests.api.test_risk_evaluations import FakeAIServiceClient
from tests.daily_record_contract import canonical_daily_record_payload

SIGNUP_PATH = "/auth/signup"
LOGIN_PATH = "/auth/login"
CONSENT_PATH = "/api/v1/consents"
BEHAVIORAL_PATH = "/api/v1/behavioral-records"
BASELINE_PATH = "/api/v1/baselines"
EMOTION_PATH = "/api/v1/emotion-analyses"
RISK_PATH = "/api/v1/risk-evaluations"
REPORT_PATH = "/api/v1/recovery-reports"
DASHBOARD_PATH = "/api/v1/dashboard"
READINESS_PATH = "/api/v1/readiness"
PASSWORD = "correct-horse-battery-staple1!"
CONSENT_TYPES = ("health_data", "emotion_diary")


class DemoFlowAIServiceClient(FakeAIServiceClient, SuccessfulReportClient):
    """감정 분류와 회복 리포트 생성을 모두 받는 단일 페이크.

    두 기능의 페이크는 이미 엔드포인트별 테스트 파일에 하나씩 있다. 데모
    흐름은 한 세션 안에서 둘 다 호출하므로 세 번째 페이크를 새로 쓰는 대신
    기존 두 개를 그대로 합친다.
    """


def signup_and_login(
    client: TestClient,
    *,
    email: str,
) -> tuple[dict[str, str], str]:
    signup = client.post(
        SIGNUP_PATH,
        json={"email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201, signup.text
    login = client.post(
        LOGIN_PATH,
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    return (
        {"Authorization": f"Bearer {login.json()['access_token']}"},
        cast(str, signup.json()["id"]),
    )


def grant_pipeline_consents(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    for consent_type in CONSENT_TYPES:
        response = client.post(
            CONSENT_PATH,
            headers=headers,
            json={"consent_type": consent_type, "source": "e2e_demo_flow"},
        )
        assert response.status_code == 201, response.text


def post_daily_record(
    client: TestClient,
    headers: dict[str, str],
    *,
    record_date: date,
    **overrides: object,
) -> None:
    response = client.post(
        BEHAVIORAL_PATH,
        headers=headers,
        json=canonical_daily_record_payload(
            record_date=record_date.isoformat(),
            **overrides,
        ),
    )
    assert response.status_code == 201, response.text


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


def test_demo_flow_chains_every_endpoint_from_signup_to_dashboard(
    client: TestClient,
    test_app: FastAPI,
) -> None:
    headers, user_id = signup_and_login(
        client,
        email="e2e-demo-flow@example.com",
    )
    grant_pipeline_consents(client, headers)

    assert readiness_state(client, headers) == "insufficient_records"

    # 평가일은 오늘(UTC)이어야 대시보드의 today_recorded가 실제로 켜진다.
    # baseline은 평가일보다 엄격히 앞선 window_end를 요구하므로, 평가일 직전
    # MINIMUM_SAMPLE_DAYS일치를 쌓고 평가일 하루를 따로 얹는다.
    evaluation_date = datetime.now(UTC).date()
    baseline_as_of = evaluation_date - timedelta(days=1)
    for offset in range(MINIMUM_SAMPLE_DAYS, 0, -1):
        post_daily_record(
            client,
            headers,
            record_date=evaluation_date - timedelta(days=offset),
        )
    # 평가일만 평소 기준보다 나쁘게 넣어야 위험 요인이 실제로 산출된다.
    post_daily_record(
        client,
        headers,
        record_date=evaluation_date,
        sleep_minutes=300,
        work_or_study_minutes=600,
        rest_minutes=20,
        exercise_minutes=10,
        schedule_count=8,
        subjective_fatigue=9.0,
    )

    assert readiness_state(client, headers) == "baseline_pending"

    baseline = client.post(
        BASELINE_PATH,
        headers=headers,
        json={"as_of_date": baseline_as_of.isoformat()},
    )
    assert baseline.status_code == 201, baseline.text
    assert baseline.json()["status"] == "ready"
    assert baseline.json()["sample_days"] == MINIMUM_SAMPLE_DAYS

    assert readiness_state(client, headers) == "baseline_ready"

    test_app.dependency_overrides[get_ai_service_client] = lambda: cast(
        AIServiceClient,
        DemoFlowAIServiceClient(),
    )
    emotion = client.post(
        EMOTION_PATH,
        headers=headers,
        json={
            "record_date": evaluation_date.isoformat(),
            "hs01": "요즘 할 일이 계속 밀리는 기분이었다",
            "hs02": "그래도 오늘은 잠깐이라도 쉬려고 했다",
        },
    )
    assert emotion.status_code == 201, emotion.text
    assert emotion.json()["record_date"] == evaluation_date.isoformat()

    evaluation = client.post(
        RISK_PATH,
        headers=headers,
        json={"date": evaluation_date.isoformat()},
    )
    assert evaluation.status_code == 201, evaluation.text
    evaluation_body = evaluation.json()
    assert evaluation_body["user_id"] == user_id
    assert evaluation_body["date"] == evaluation_date.isoformat()
    # 앞 단계 산출물이 그대로 provenance로 들어왔는지 — 이 두 줄이 없으면
    # 각 엔드포인트가 개별적으로 통과해도 연결이 끊긴 걸 알 수 없다.
    assert evaluation_body["emotion_analysis_id"] == emotion.json()["id"]
    assert evaluation_body["baseline_id"] == baseline.json()["id"]
    assert evaluation_body["result"]["level"] in {
        level.value for level in RiskLevel
    }

    assert readiness_state(client, headers) == "risk_evaluation_ready"

    report = client.post(
        REPORT_PATH,
        headers=headers,
        json={"risk_evaluation_id": evaluation_body["id"]},
    )
    assert report.status_code == 201, report.text
    report_body = report.json()
    assert report_body["risk_evaluation_id"] == evaluation_body["id"]
    assert report_body["generation_status"] == "llm_generated"
    assert report_body["period_end"] == evaluation_date.isoformat()

    assert readiness_state(client, headers) == "recovery_report_ready"

    body = dashboard_body(client, headers)
    assert body["record_status"] == {
        "today_recorded": True,
        "recorded_days": MINIMUM_SAMPLE_DAYS + 1,
    }
    assert body["baseline"] == {
        "status": "ready",
        "sample_days": MINIMUM_SAMPLE_DAYS,
        "window_end": baseline_as_of.isoformat(),
        "created_at": baseline.json()["created_at"],
    }
    assert body["latest_risk"] == {
        "level": evaluation_body["result"]["level"],
        "date": evaluation_date.isoformat(),
        "top_factors": [
            factor["code"]
            for factor in evaluation_body["result"]["factors"][:3]
        ],
    }
    assert body["latest_report"]["id"] == report_body["id"]
    assert body["latest_report"]["generation_status"] == "llm_generated"


def test_pipeline_first_write_no_longer_requires_health_data_consent(
    client: TestClient,
) -> None:
    """생활 기록 직접 입력은 health_data 동의와 무관하다.

    health_data("건강·생활 데이터 활용 동의")는 저장된 데이터를 분석에
    "활용"하는 것에 대한 동의이지, 손으로 남기는 기록 자체를 막는
    전제조건이 아니다. Samsung Health 자동 동기화 동의 여부와 직접 입력
    권한을 분리한 이후로는 동의 없이도 파이프라인의 첫 쓰기가 성공한다.

    다만 마음 기록(감정 분석)은 여전히 emotion_diary 동의를 요구한다 --
    동의가 파이프라인 중간 단계에 실제로 영향을 준다는 근거는 남겨둔다.
    """

    headers, _ = signup_and_login(
        client,
        email="e2e-demo-flow-no-consent@example.com",
    )
    record_date = datetime.now(UTC).date()

    behavioral_response = client.post(
        BEHAVIORAL_PATH,
        headers=headers,
        json=canonical_daily_record_payload(
            record_date=record_date.isoformat(),
        ),
    )
    assert behavioral_response.status_code == 201, behavioral_response.text
    # 하루치 기록만으로는 여전히 리포트를 만들 만큼 충분하지 않다 -- 동의
    # 여부가 아니라 기록 일수 부족으로 여기서 막힌다.
    assert readiness_state(client, headers) == "insufficient_records"

    emotion_response = client.post(
        EMOTION_PATH,
        headers=headers,
        json={
            "record_date": record_date.isoformat(),
            "hs01": "오늘 있었던 일",
            "hs02": "그때 든 생각이나 느낌",
        },
    )
    assert emotion_response.status_code == 403
    assert emotion_response.json() == {"detail": "emotion_diary 동의가 필요합니다"}
