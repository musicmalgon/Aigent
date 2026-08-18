"""`DELETE /users/me/data` — 건강/행동 파생 데이터만 지우고 계정과 동의는 남긴다.

이 파일이 지키려는 것은 "무엇이 지워지는가"보다 "무엇이 지워지지 *않는가*"다.
동의 이력과 계정 행이 실수로 함께 사라지는 회귀를 잡는 것이 목적이므로,
삭제 후 상태는 응답 본문이 아니라 DB를 직접 조회해서 확인한다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models.consent import ConsentRecord
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    EmotionAnalysisResult,
    PersistenceBaselineStatus,
    RecoveryReport,
)
from tests.daily_record_contract import canonical_daily_record_payload

BASE_PATH = "/users/me/data"
USER_PATH = "/users/me"
CONSENT_PATH = "/api/v1/consents"
BEHAVIORAL_PATH = "/api/v1/behavioral-records"
PASSWORD = "correct-horse-battery-staple1!"
CONSENT_TYPES = ("health_data", "emotion_diary")
RECORD_DATES = (date(2026, 7, 18), date(2026, 7, 19), date(2026, 7, 20))

DELETED_MODELS = (
    RecoveryReport,
    BurnoutRiskEvaluation,
    BehavioralBaseline,
    EmotionAnalysisResult,
    BehavioralDailyRecord,
)


def signup_and_login(
    client: TestClient,
    *,
    email: str,
) -> tuple[dict[str, str], str]:
    credentials = {"email": email, "password": PASSWORD}
    signup = client.post("/auth/signup", json=credentials)
    assert signup.status_code == 201, signup.text
    login = client.post("/auth/login", json=credentials)
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, str(signup.json()["id"])


def grant_consents(client: TestClient, headers: dict[str, str]) -> None:
    for consent_type in CONSENT_TYPES:
        response = client.post(
            CONSENT_PATH,
            headers=headers,
            json={"consent_type": consent_type, "source": "account_deletion_test"},
        )
        assert response.status_code == 201, response.text


def post_daily_records(client: TestClient, headers: dict[str, str]) -> None:
    for record_date in RECORD_DATES:
        response = client.post(
            BEHAVIORAL_PATH,
            headers=headers,
            json=canonical_daily_record_payload(
                record_date=record_date.isoformat(),
            ),
        )
        assert response.status_code == 201, response.text


def seed_derived_rows(engine: Engine, *, user_id: str) -> None:
    """감정/기준선/위험도/리포트를 ORM으로 직접 심는다.

    이 테스트의 관심사는 삭제 엔드포인트이지 파이프라인이 아니다. 파이프라인이
    실제로 이어지는지는 `test_e2e_demo_flow.py`가 이미 증명하므로, 여기서는
    AI 페이크와 전제 조건(기준선 window_end < 평가일 등)을 다시 세우는 대신
    최소한의 유효한 행만 만든다.
    """

    record_date = RECORD_DATES[-1]
    with Session(engine) as session:
        daily_record_id = session.scalar(
            select(BehavioralDailyRecord.id).where(
                BehavioralDailyRecord.user_id == user_id,
                BehavioralDailyRecord.record_date == record_date,
            )
        )
        assert daily_record_id is not None

        emotion = EmotionAnalysisResult(
            user_id=user_id,
            record_date=record_date,
            analyzed_at=datetime.now(UTC),
            model_version="test-emotion-1",
            taxonomy_version="v1",
            predicted_emotion="불안",
            emotion="불안",
            confidence=0.82,
            is_uncertain=False,
            probabilities={"불안": 0.82, "기쁨": 0.18},
            provisional=False,
        )
        baseline = BehavioralBaseline(
            user_id=user_id,
            window_start=record_date - timedelta(days=6),
            window_end=record_date - timedelta(days=1),
            sample_days=7,
            sleep_minutes=420.0,
            status=PersistenceBaselineStatus.READY,
            algorithm_version="test-baseline-1",
        )
        session.add_all([emotion, baseline])
        session.flush()

        evaluation = BurnoutRiskEvaluation(
            user_id=user_id,
            record_date=record_date,
            evaluated_at=datetime.now(UTC),
            daily_record_id=daily_record_id,
            emotion_analysis_result_id=emotion.id,
            baseline_id=baseline.id,
            engine_version="test-engine-1",
            score=42.0,
            level="moderate",
            is_provisional=False,
            baseline_status="ready",
            data_quality="sufficient",
            category_scores={"sleep": 12.0, "rest": 8.0},
            factors=[],
            summary={"headline": "테스트 요약"},
        )
        session.add(evaluation)
        session.flush()

        session.add(
            RecoveryReport(
                user_id=user_id,
                risk_evaluation_id=evaluation.id,
                period_start=record_date - timedelta(days=6),
                period_end=record_date,
                facts={},
                selected_actions=[],
                content={"headline": "테스트 리포트"},
                disclaimer="의료적 진단이 아닙니다",
                generation_status="template_fallback",
                catalog_version="test-catalog-1",
                prompt_version="test-prompt-1",
                model_name=None,
                generated_at=datetime.now(UTC),
            )
        )
        session.commit()


def row_counts(engine: Engine, *, user_id: str) -> dict[str, int]:
    with Session(engine) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.user_id == user_id)
            )
            or 0
            for model in DELETED_MODELS
        }


def seeded_user(
    client: TestClient,
    engine: Engine,
    *,
    email: str,
) -> tuple[dict[str, str], str]:
    headers, user_id = signup_and_login(client, email=email)
    grant_consents(client, headers)
    post_daily_records(client, headers)
    seed_derived_rows(engine, user_id=user_id)
    return headers, user_id


def delete_account_data(
    client: TestClient,
    headers: dict[str, str] | None,
    *,
    password: str = PASSWORD,
) -> httpx.Response:
    # httpx의 delete()는 본문을 받지 않으므로 request()로 보낸다.
    return client.request(
        "DELETE",
        BASE_PATH,
        headers=headers or {},
        json={"current_password": password},
    )


FULL_SEED_COUNTS = {
    "recovery_reports": 1,
    "burnout_risk_evaluations": 1,
    "behavioral_baselines": 1,
    "emotion_analysis_results": 1,
    "behavioral_daily_records": len(RECORD_DATES),
}


def test_deletes_every_derived_table_and_reports_counts(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = seeded_user(
        client,
        migrated_engine,
        email="account-deletion-happy@example.com",
    )
    assert row_counts(migrated_engine, user_id=user_id) == FULL_SEED_COUNTS

    response = delete_account_data(client, headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "recovery_reports_deleted": 1,
        "risk_evaluations_deleted": 1,
        "baselines_deleted": 1,
        "emotion_analyses_deleted": 1,
        "daily_records_deleted": len(RECORD_DATES),
    }
    # 응답 본문을 믿지 않고 DB를 직접 본다.
    assert row_counts(migrated_engine, user_id=user_id) == dict.fromkeys(
        FULL_SEED_COUNTS,
        0,
    )


def test_consent_records_survive_deletion(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    """이 기능이 존재하는 이유 그 자체 — 동의 이력은 삭제 대상이 아니다."""

    headers, user_id = seeded_user(
        client,
        migrated_engine,
        email="account-deletion-consent@example.com",
    )

    assert delete_account_data(client, headers).status_code == 200

    consents = client.get(CONSENT_PATH, headers=headers)
    assert consents.status_code == 200, consents.text
    assert {row["consent_type"] for row in consents.json()} == set(CONSENT_TYPES)
    assert all(row["status"] == "granted" for row in consents.json())

    with Session(migrated_engine) as session:
        stored = session.scalar(
            select(func.count())
            .select_from(ConsentRecord)
            .where(ConsentRecord.user_id == user_id)
        )
    assert stored == len(CONSENT_TYPES)


def test_user_account_survives_deletion(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = seeded_user(
        client,
        migrated_engine,
        email="account-deletion-account@example.com",
    )

    assert delete_account_data(client, headers).status_code == 200

    # 같은 토큰이 그대로 통해야 한다 — 삭제는 로그아웃도 탈퇴도 아니다.
    me = client.get(USER_PATH, headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["id"] == user_id
    assert me.json()["email"] == "account-deletion-account@example.com"


def test_wrong_password_deletes_nothing(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = seeded_user(
        client,
        migrated_engine,
        email="account-deletion-wrong-password@example.com",
    )

    response = delete_account_data(
        client,
        headers,
        password="wrong-horse-battery-staple9!",
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "현재 비밀번호가 일치하지 않습니다"}
    # 인증 검사가 삭제보다 먼저 일어났다는 증거.
    assert row_counts(migrated_engine, user_id=user_id) == FULL_SEED_COUNTS


def test_deletion_is_scoped_to_the_requesting_user(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, _ = seeded_user(
        client,
        migrated_engine,
        email="account-deletion-owner@example.com",
    )
    _, other_user_id = seeded_user(
        client,
        migrated_engine,
        email="account-deletion-bystander@example.com",
    )

    assert delete_account_data(client, headers).status_code == 200

    assert row_counts(migrated_engine, user_id=other_user_id) == FULL_SEED_COUNTS


def test_requires_authentication(client: TestClient) -> None:
    response = delete_account_data(client, None)

    assert response.status_code in {401, 403}


def test_empty_account_returns_zero_counts(client: TestClient) -> None:
    headers, _ = signup_and_login(
        client,
        email="account-deletion-empty@example.com",
    )

    response = delete_account_data(client, headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "recovery_reports_deleted": 0,
        "risk_evaluations_deleted": 0,
        "baselines_deleted": 0,
        "emotion_analyses_deleted": 0,
        "daily_records_deleted": 0,
    }
