from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi.testclient import TestClient

from app.services.baselines import MINIMUM_SAMPLE_DAYS
from app.services.kbat_result import KBAT_SURVEY_SOURCE
from tests.api.test_dashboard import authenticated_user, post_daily_record

ANCHOR_PATH = "/assessments/anchor"
KBAT_RESULT_PATH = "/assessments/kbat-result"
COMPLETED_AT = "2026-08-10T09:00:00+09:00"


def submit_kbat_survey(
    client: TestClient,
    headers: dict[str, str],
    *,
    exhaustion: float,
    mental_distance: float,
    cognitive_control: float,
    emotional_control: float,
) -> dict[str, Any]:
    response = client.post(
        ANCHOR_PATH,
        headers=headers,
        json={
            "assessment_type": "k_bat",
            "target_group": "university_student",
            "completed_at": COMPLETED_AT,
            "dimensions": {
                "exhaustion": exhaustion,
                "mental_distance": mental_distance,
                "cognitive_control": cognitive_control,
                "emotional_control": emotional_control,
            },
            "source": KBAT_SURVEY_SOURCE,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def seed_daily_records(
    client: TestClient,
    headers: dict[str, str],
    *,
    days: int,
) -> None:
    today = datetime.now(UTC).date()
    for offset in range(days):
        post_daily_record(
            client,
            headers,
            record_date=(today - timedelta(days=offset)).isoformat(),
        )


def test_kbat_result_is_not_taken_for_a_fresh_user(client: TestClient) -> None:
    headers, _ = authenticated_user(client, email="kbat-fresh@example.com")

    response = client.get(KBAT_RESULT_PATH, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "state": "not_taken",
        "recorded_days": 0,
        "minimum_required_days": MINIMUM_SAMPLE_DAYS,
        "survey_completed_at": None,
        "result": None,
    }


def test_kbat_result_stays_insufficient_until_seven_actual_record_days(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client, email="kbat-insufficient@example.com")
    submit_kbat_survey(
        client,
        headers,
        exhaustion=3.0,
        mental_distance=3.0,
        cognitive_control=3.0,
        emotional_control=3.0,
    )
    seed_daily_records(client, headers, days=MINIMUM_SAMPLE_DAYS - 1)

    response = client.get(KBAT_RESULT_PATH, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "insufficient_records"
    assert body["recorded_days"] == MINIMUM_SAMPLE_DAYS - 1
    assert body["result"] is None
    # 설문 자체는 완료했으므로 완료 시각은 이미 알고 있다.
    assert body["survey_completed_at"] is not None


def test_kbat_result_becomes_ready_once_seven_days_are_recorded(
    client: TestClient,
) -> None:
    headers, _ = authenticated_user(client, email="kbat-ready@example.com")
    submit_kbat_survey(
        client,
        headers,
        exhaustion=4.0,
        mental_distance=2.0,
        cognitive_control=2.0,
        emotional_control=2.0,
    )
    seed_daily_records(client, headers, days=MINIMUM_SAMPLE_DAYS)

    response = client.get(KBAT_RESULT_PATH, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "ready"
    assert body["recorded_days"] == MINIMUM_SAMPLE_DAYS
    assert body["result"] == {
        "exhaustion_average": 4.0,
        "mental_distance_average": 2.0,
        "cognitive_control_average": 2.0,
        "emotional_control_average": 2.0,
        "total_average": 2.5,
        "risk_level": "good",
    }


def test_kbat_result_boundary_classification_matches_the_spec_table(
    client: TestClient,
) -> None:
    cases = [
        (1.00, "good"),
        (2.53, "good"),
        (2.54, "caution"),
        (2.95, "caution"),
        (2.96, "warning"),
        (5.00, "warning"),
    ]
    for value, expected_level in cases:
        headers, _ = authenticated_user(
            client,
            email=f"kbat-boundary-{str(value).replace('.', '-')}@example.com",
        )
        submit_kbat_survey(
            client,
            headers,
            exhaustion=value,
            mental_distance=value,
            cognitive_control=value,
            emotional_control=value,
        )
        seed_daily_records(client, headers, days=MINIMUM_SAMPLE_DAYS)

        body = client.get(KBAT_RESULT_PATH, headers=headers).json()
        assert body["result"]["risk_level"] == expected_level, value
        assert body["result"]["total_average"] == value


def test_kbat_result_ignores_pre_v2_kbat_anchors(client: TestClient) -> None:
    """예전 채점 방식(0~1 소진 강도 반전 환산)으로 저장된 K-BAT 응답은
    새 결과 계산에 섞이지 않아야 한다 -- 기존 사용자 데이터 호환성."""
    headers, _ = authenticated_user(client, email="kbat-legacy@example.com")
    legacy = client.post(
        ANCHOR_PATH,
        headers=headers,
        json={
            "assessment_type": "k_bat",
            "target_group": "university_student",
            "completed_at": COMPLETED_AT,
            "dimensions": {
                "exhaustion": 0.75,
                "mental_distance": 0.5,
                "cognitive_control": 0.25,
                "emotional_control": 0.5,
            },
            "source": "onboarding_kbat_v1",
        },
    )
    assert legacy.status_code == 201, legacy.text
    seed_daily_records(client, headers, days=MINIMUM_SAMPLE_DAYS)

    response = client.get(KBAT_RESULT_PATH, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "not_taken"


def test_kbat_result_requires_authentication(client: TestClient) -> None:
    assert client.get(KBAT_RESULT_PATH).status_code == 401


def test_kbat_result_never_reflects_another_users_data(
    client: TestClient,
) -> None:
    owner_headers, _ = authenticated_user(client, email="kbat-owner@example.com")
    other_headers, _ = authenticated_user(client, email="kbat-other@example.com")
    submit_kbat_survey(
        client,
        owner_headers,
        exhaustion=5.0,
        mental_distance=5.0,
        cognitive_control=5.0,
        emotional_control=5.0,
    )
    seed_daily_records(client, owner_headers, days=MINIMUM_SAMPLE_DAYS)

    other_body = client.get(KBAT_RESULT_PATH, headers=other_headers).json()
    assert other_body["state"] == "not_taken"

    owner_body = client.get(KBAT_RESULT_PATH, headers=owner_headers).json()
    assert owner_body["state"] == "ready"
    assert owner_body["result"]["risk_level"] == "warning"
