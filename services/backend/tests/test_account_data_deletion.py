"""`DELETE /users/me/data` — 파생 데이터와 계정 자체를 모두 지운다.

원래는 파생 데이터만 지우고 계정과 동의 이력은 감사 추적을 위해 보존했었다.
하지만 그 설계가 프론트 UI 문구("계정 삭제")와 어긋난다는 문제(#133)로,
계정 자체도 지우는 진짜 삭제로 바뀌었다. 이 파일이 지금 지키려는 것은
"users.id를 참조하는 모든 것 -- 파생 데이터 5개 + 동의 이력 + 검사 응답 --
이 계정과 함께 남김없이 지워지고, 삭제 후엔 기존 토큰이 더는 통하지 않는다"
는 것이다. 삭제 후 상태는 응답 본문이 아니라 DB를 직접 조회해서도 확인한다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models.assessment import AssessmentAnchor
from app.models.consent import ConsentRecord
from app.models.persistence import (
    BehavioralBaseline,
    BehavioralDailyRecord,
    BurnoutRiskEvaluation,
    EmotionAnalysisResult,
    PersistenceBaselineStatus,
    RecoveryReport,
)
from app.models.user import User
from tests.daily_record_contract import canonical_daily_record_payload

BASE_PATH = "/users/me/data"
USER_PATH = "/users/me"
CONSENT_PATH = "/api/v1/consents"
BEHAVIORAL_PATH = "/api/v1/behavioral-records"
ASSESSMENT_PATH = "/assessments/anchor"
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


def post_assessment_anchor(
    client: TestClient,
    headers: dict[str, str],
    *,
    supersedes_id: str | None = None,
) -> str:
    response = client.post(
        ASSESSMENT_PATH,
        headers=headers,
        json={
            "assessment_type": "k_bat",
            "target_group": "university_student",
            "completed_at": datetime.now(UTC).isoformat(),
            "dimensions": {
                "exhaustion": 2.0,
                "academic_burden": 1.5,
                "occupational_burden": None,
                "recovery_difficulty": 1.0,
            },
            "source": "account_deletion_test",
            "supersedes_id": supersedes_id,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def seed_assessment_anchors(client: TestClient, headers: dict[str, str]) -> None:
    # 재검사가 이전 검사를 대체하는 흔한 케이스를 재현한다 -- supersedes_id로
    # 같은 사용자의 다른 행을 자기참조하는 체인. 삭제 시 이 자기참조가 먼저
    # 안 끊기면 FK 제약(SQLite도 PRAGMA foreign_keys=ON)에 걸릴 수 있어서,
    # 이 체인이 있는 채로 삭제가 되는지가 이 테스트의 핵심이다.
    first_id = post_assessment_anchor(client, headers)
    post_assessment_anchor(client, headers, supersedes_id=first_id)


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


def count_rows(engine: Engine, model: type, *, user_id: str) -> int:
    with Session(engine) as session:
        return (
            session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user_id)
            )
            or 0
        )


def user_exists(engine: Engine, *, user_id: str) -> bool:
    with Session(engine) as session:
        return session.scalar(select(User).where(User.id == user_id)) is not None


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
    seed_assessment_anchors(client, headers)
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
    assert count_rows(migrated_engine, ConsentRecord, user_id=user_id) == len(
        CONSENT_TYPES
    )
    assert count_rows(migrated_engine, AssessmentAnchor, user_id=user_id) == 2

    response = delete_account_data(client, headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "recovery_plan_items_deleted": 0,
        "recovery_reports_deleted": 1,
        "risk_evaluations_deleted": 1,
        "baselines_deleted": 1,
        "emotion_analyses_deleted": 1,
        "daily_records_deleted": len(RECORD_DATES),
        "consent_records_deleted": len(CONSENT_TYPES),
        "assessment_anchors_deleted": 2,
    }
    # 응답 본문을 믿지 않고 DB를 직접 본다.
    assert row_counts(migrated_engine, user_id=user_id) == dict.fromkeys(
        FULL_SEED_COUNTS,
        0,
    )
    assert count_rows(migrated_engine, ConsentRecord, user_id=user_id) == 0
    assert count_rows(migrated_engine, AssessmentAnchor, user_id=user_id) == 0


def test_consent_records_are_deleted_with_account(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    """이전엔 동의 이력이 감사 추적용으로 살아남았지만(#133 이전), 계정
    자체를 지우는 진짜 삭제로 바뀌면서 재로그인이 불가능해져 감사 추적을
    남겨둘 이유도 함께 사라졌다."""

    headers, user_id = seeded_user(
        client,
        migrated_engine,
        email="account-deletion-consent@example.com",
    )

    assert delete_account_data(client, headers).status_code == 200

    # 계정 자체가 지워졌으므로 그 토큰으로는 더 이상 아무 것도 조회할 수 없다.
    consents = client.get(CONSENT_PATH, headers=headers)
    assert consents.status_code == 401, consents.text

    assert count_rows(migrated_engine, ConsentRecord, user_id=user_id) == 0


def test_user_account_is_deleted(
    client: TestClient,
    migrated_engine: Engine,
) -> None:
    headers, user_id = seeded_user(
        client,
        migrated_engine,
        email="account-deletion-account@example.com",
    )

    assert delete_account_data(client, headers).status_code == 200

    # 기존 토큰은 더 이상 통하지 않는다 -- 계정이 실제로 지워졌다는 증거.
    me = client.get(USER_PATH, headers=headers)
    assert me.status_code == 401, me.text
    assert not user_exists(migrated_engine, user_id=user_id)

    # 같은 이메일로 새로 가입할 수 있어야 한다 (계정이 정말 비어있다는 증거).
    resignup = client.post(
        "/auth/signup",
        json={"email": "account-deletion-account@example.com", "password": PASSWORD},
    )
    assert resignup.status_code == 201, resignup.text


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
    assert user_exists(migrated_engine, user_id=user_id)


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
    assert user_exists(migrated_engine, user_id=other_user_id)


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
        "recovery_plan_items_deleted": 0,
        "recovery_reports_deleted": 0,
        "risk_evaluations_deleted": 0,
        "baselines_deleted": 0,
        "emotion_analyses_deleted": 0,
        "daily_records_deleted": 0,
        "consent_records_deleted": 0,
        "assessment_anchors_deleted": 0,
    }
