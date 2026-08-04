"""학술제 시연용 데모 데이터 시드 스크립트.

`services/backend`에서 다음과 같이 실행한다::

    python -m app.scripts.seed_demo_data

설정된 `DATABASE_URL`(기본값 `sqlite:///./remind.db`)에 직접 붙어서 아래 세 개의
데모 계정을 만든다. 모든 산출물(baseline / risk evaluation / recovery report)은
API 핸들러가 호출하는 것과 동일한 서비스 함수를 그대로 거쳐 생성된다. 미리 계산해
둔 결과를 테이블에 꽂아 넣지 않는다.

데모 계정 (비밀번호는 셋 다 `Demo1234!`):

- `demo-insufficient@remind.example`
  기록 부족 — readiness `insufficient_records`
- `demo-normal@remind.example`
  정상 패턴 + READY baseline — readiness `baseline_ready`
- `demo-high-risk@remind.example`
  수면·휴식 감소로 위험도 상승 + 회복 리포트 — readiness `recovery_report_ready`

세 계정 모두 `health_data` 동의가 부여된 상태로 만들어지므로, 시드 후 실제 API로
로그인해서 기록을 추가해도 동의 게이트에 막히지 않는다.

Recovery Report는 AI 서비스가 떠 있고 `GEMINI_API_KEY`가 설정되어 있으면
`llm_generated`, 아니면 `template_fallback`으로 저장된다. 둘 다 정상이다.
감정 분석은 "생성된 감정 결과를 절대 조작하지 않는다"는 제약 때문에 AI 서비스가
실제로 응답할 때만 시도하고, 아니면 조용히 건너뛴다.

같은 이메일의 계정이 이미 있으면 해당 시나리오 전체를 건너뛰므로 재실행해도 안전하다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.clients.ai import (
    AIServiceClient,
    CoarseEmotionRequest,
    create_ai_service_client,
)
from app.core.config import Settings
from app.core.database import create_database_engine
from app.core.security import hash_password
from app.models.consent import ConsentRecord, ConsentStatus, ConsentType
from app.models.user import User, UserType
from app.repositories.behavioral_records import create_daily_record
from app.schemas.behavioral_records import (
    BEHAVIORAL_FIELD_NAMES,
    CoverageByField,
    DailyRecordCreate,
    DataCoverage,
    DataSource,
    SourceByField,
)
from app.services.baselines import (
    DEFAULT_WINDOW_DAYS,
    MINIMUM_SAMPLE_DAYS,
    calculate_and_store_baseline,
)
from app.services.behavioral_record_mapper import to_persistence_create
from app.services.emotion_analysis import analyze_and_stage_emotion_result
from app.services.recovery_reports import (
    generate_recovery_report_copy,
    prepare_recovery_report,
    store_prepared_recovery_report,
)
from app.services.risk_evaluation import (
    evaluate_prepared_risk,
    prepare_risk_evaluation,
    store_prepared_risk_evaluation,
)

INSUFFICIENT_EMAIL = "demo-insufficient@remind.example"
NORMAL_EMAIL = "demo-normal@remind.example"
HIGH_RISK_EMAIL = "demo-high-risk@remind.example"
DEMO_PASSWORD = "Demo1234!"

DEMO_TIME_ZONE = "Asia/Seoul"
CONSENT_SOURCE = "demo-seed-script"

# 기록 부족 판정은 services/baselines.py의 임계값을 그대로 따라간다.
INSUFFICIENT_RECORD_DAYS = MINIMUM_SAMPLE_DAYS - 3
# 최근 며칠을 "악화 구간"으로 둘지. baseline 윈도우와 겹치면 평소 기준 자체가
# 같이 나빠져 변화량이 사라지므로, 악화 구간은 baseline 윈도우 바깥에 둔다.
DECLINE_DAYS = 7
HISTORY_DAYS = DEFAULT_WINDOW_DAYS + DECLINE_DAYS


@dataclass(frozen=True)
class DayProfile:
    """하루치 생활 기록의 기준값. 실제 저장 값은 여기에 소폭 변동을 더한다."""

    sleep_minutes: int
    bedtime: time
    wake_time: time
    steps: int
    active_minutes: int
    exercise_minutes: int
    work_or_study_minutes: int
    rest_minutes: int
    schedule_count: int
    subjective_fatigue: float


STABLE_DAY = DayProfile(
    sleep_minutes=420,
    bedtime=time(23, 30),
    wake_time=time(6, 30),
    steps=7200,
    active_minutes=50,
    exercise_minutes=30,
    work_or_study_minutes=420,
    rest_minutes=120,
    schedule_count=3,
    subjective_fatigue=3.0,
)

STRAINED_DAY = DayProfile(
    sleep_minutes=300,
    bedtime=time(1, 30),
    wake_time=time(6, 30),
    steps=3800,
    active_minutes=20,
    exercise_minutes=5,
    work_or_study_minutes=540,
    rest_minutes=30,
    schedule_count=5,
    subjective_fatigue=8.0,
)

EMOTION_DIARY = CoarseEmotionRequest(
    hs01="요즘 과제랑 아르바이트가 겹쳐서 잠을 제대로 못 자고 있어요.",
    hs02="쉬는 시간을 만들어도 마음이 편하지 않고 계속 지쳐 있는 느낌이에요.",
    hs03="이번 주에는 아무것도 하기 싫다는 생각이 자주 들어요.",
)


def _record_metadata() -> tuple[SourceByField, CoverageByField]:
    return (
        SourceByField(
            **{name: DataSource.MANUAL for name in BEHAVIORAL_FIELD_NAMES}
        ),
        CoverageByField(
            **{name: DataCoverage.COMPLETE for name in BEHAVIORAL_FIELD_NAMES}
        ),
    )


def _daily_payload(
    profile: DayProfile,
    *,
    record_date: date,
    index: int,
) -> DailyRecordCreate:
    # -1 / 0 / +1이 반복되도록 해서 사람이 만든 것 같은 흔들림을 주되,
    # 윈도우 평균이 프로파일 기준값에서 사실상 벗어나지 않게 한다.
    shift = (index % 3) - 1
    source_by_field, coverage_by_field = _record_metadata()
    return DailyRecordCreate(
        date=record_date,
        time_zone=DEMO_TIME_ZONE,
        sleep_minutes=profile.sleep_minutes + shift * 10,
        bedtime=profile.bedtime,
        wake_time=profile.wake_time,
        steps=profile.steps + shift * 250,
        active_minutes=max(0, profile.active_minutes + shift * 5),
        exercise_minutes=max(0, profile.exercise_minutes + shift * 5),
        work_or_study_minutes=profile.work_or_study_minutes + shift * 20,
        rest_minutes=max(0, profile.rest_minutes + shift * 10),
        schedule_count=max(0, profile.schedule_count + shift),
        subjective_fatigue=max(0.0, profile.subjective_fatigue + shift * 0.5),
        source_by_field=source_by_field,
        coverage_by_field=coverage_by_field,
    )


def _find_user(session: Session, email: str) -> User | None:
    return session.query(User).filter(User.email == email).first()


def _create_user(
    session: Session,
    *,
    email: str,
    name: str,
    user_type: UserType,
) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(DEMO_PASSWORD),
        name=name,
        user_type=user_type,
    )
    session.add(user)
    session.flush()
    return user


def _grant_consent(
    session: Session,
    *,
    user_id: str,
    consent_type: ConsentType,
) -> None:
    session.add(
        ConsentRecord(
            user_id=user_id,
            consent_type=consent_type,
            status=ConsentStatus.GRANTED,
            granted_at=datetime.now(UTC),
            withdrawn_at=None,
            source=CONSENT_SOURCE,
        )
    )


def _insert_daily_records(
    session: Session,
    *,
    user_id: str,
    profiles: list[tuple[date, DayProfile]],
) -> None:
    for index, (record_date, profile) in enumerate(profiles):
        create_daily_record(
            session,
            user_id=user_id,
            payload=to_persistence_create(
                _daily_payload(profile, record_date=record_date, index=index)
            ),
        )


def seed_insufficient_records_user(
    session: Session,
    *,
    anchor_date: date | None = None,
) -> bool:
    """기록이 baseline 최소 표본에 못 미치는 계정. 파생 산출물을 만들지 않는다."""

    anchor = anchor_date or datetime.now(UTC).date()
    if _find_user(session, INSUFFICIENT_EMAIL) is not None:
        print(f"[skip] {INSUFFICIENT_EMAIL} 계정이 이미 있어 건너뜁니다.")
        return False

    user = _create_user(
        session,
        email=INSUFFICIENT_EMAIL,
        name="기록부족 데모",
        user_type=UserType.UNIVERSITY_STUDENT,
    )
    _grant_consent(
        session,
        user_id=user.id,
        consent_type=ConsentType.HEALTH_DATA,
    )
    _insert_daily_records(
        session,
        user_id=user.id,
        profiles=[
            (anchor - timedelta(days=offset), STABLE_DAY)
            for offset in reversed(range(INSUFFICIENT_RECORD_DAYS))
        ],
    )
    session.commit()
    print(
        f"[ok] {INSUFFICIENT_EMAIL}: 기록 {INSUFFICIENT_RECORD_DAYS}일 "
        f"(최소 표본 {MINIMUM_SAMPLE_DAYS}일 미만), 파생 산출물 없음"
    )
    return True


def seed_normal_pattern_user(
    session: Session,
    *,
    anchor_date: date | None = None,
) -> bool:
    """안정적인 패턴으로 READY baseline까지만 만드는 계정."""

    anchor = anchor_date or datetime.now(UTC).date()
    if _find_user(session, NORMAL_EMAIL) is not None:
        print(f"[skip] {NORMAL_EMAIL} 계정이 이미 있어 건너뜁니다.")
        return False

    user = _create_user(
        session,
        email=NORMAL_EMAIL,
        name="정상패턴 데모",
        user_type=UserType.EARLY_CAREER_WORKER,
    )
    _grant_consent(
        session,
        user_id=user.id,
        consent_type=ConsentType.HEALTH_DATA,
    )
    _insert_daily_records(
        session,
        user_id=user.id,
        profiles=[
            (anchor - timedelta(days=offset), STABLE_DAY)
            for offset in reversed(range(HISTORY_DAYS))
        ],
    )
    session.commit()

    baseline = calculate_and_store_baseline(
        session,
        user_id=user.id,
        window_end=anchor,
        today=anchor,
    )
    session.commit()
    print(
        f"[ok] {NORMAL_EMAIL}: 기록 {HISTORY_DAYS}일, baseline "
        f"{baseline.status.value}(sample_days={baseline.sample_days}), "
        "위험도 평가 없음"
    )
    return True


async def _try_emotion_analysis(
    session: Session,
    *,
    user_id: str,
    record_date: date,
    ai_client: AIServiceClient,
) -> bool:
    """AI 서비스가 실제로 응답할 때만 감정 분석을 남긴다.

    감정 결과는 반드시 실제 모델 출력이어야 하므로, 서비스가 없으면 위조하지 않고
    그냥 건너뛴다. 이 단계 실패가 전체 시드를 중단시켜서는 안 된다.
    """

    try:
        await ai_client.check_readiness()
        await analyze_and_stage_emotion_result(
            session,
            user_id=user_id,
            record_date=record_date,
            request=EMOTION_DIARY,
            ai_client=ai_client,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        print(
            "       감정 분석 생략 (AI 서비스 미응답): "
            f"{type(exc).__name__}"
        )
        return False
    print("       감정 분석 1건 생성 (AI 서비스 응답)")
    return True


async def seed_high_risk_user(
    session: Session,
    settings: Settings,
    *,
    anchor_date: date | None = None,
) -> bool:
    """수면·휴식이 최근 급감해 위험도가 올라가는 계정. 회복 리포트까지 만든다."""

    anchor = anchor_date or datetime.now(UTC).date()
    if _find_user(session, HIGH_RISK_EMAIL) is not None:
        print(f"[skip] {HIGH_RISK_EMAIL} 계정이 이미 있어 건너뜁니다.")
        return False

    user = _create_user(
        session,
        email=HIGH_RISK_EMAIL,
        name="위험신호 데모",
        user_type=UserType.JOB_SEEKER,
    )
    for consent_type in (ConsentType.HEALTH_DATA, ConsentType.EMOTION_DIARY):
        _grant_consent(session, user_id=user.id, consent_type=consent_type)

    # 앞쪽 DEFAULT_WINDOW_DAYS일은 건강한 패턴, 최근 DECLINE_DAYS일만 악화시킨다.
    profiles = [
        (
            anchor - timedelta(days=offset),
            STRAINED_DAY if offset < DECLINE_DAYS else STABLE_DAY,
        )
        for offset in reversed(range(HISTORY_DAYS))
    ]
    _insert_daily_records(session, user_id=user.id, profiles=profiles)
    session.commit()

    # baseline 윈도우를 악화 구간 직전에서 끊어야 "평소 기준"이 건강한 시기를
    # 가리킨다. get_latest_ready_baseline_before는 window_end < 평가일인
    # baseline만 고르므로 이 경계가 곧 평가 가능 조건이기도 하다.
    baseline_window_end = anchor - timedelta(days=DECLINE_DAYS)
    baseline = calculate_and_store_baseline(
        session,
        user_id=user.id,
        window_end=baseline_window_end,
        today=anchor,
    )
    session.commit()

    ai_client = create_ai_service_client(settings)
    try:
        await _try_emotion_analysis(
            session,
            user_id=user.id,
            record_date=anchor,
            ai_client=ai_client,
        )

        # api/risk_evaluations.py의 POST 핸들러와 동일한 3단계 순서.
        prepared_risk = prepare_risk_evaluation(
            session,
            user_id=user.id,
            record_date=anchor,
        )
        session.rollback()
        result = evaluate_prepared_risk(prepared_risk)
        evaluation = store_prepared_risk_evaluation(
            session,
            prepared=prepared_risk,
            result=result,
        )
        evaluation_id = evaluation.id
        session.commit()

        prepared_report = prepare_recovery_report(
            session,
            user_id=user.id,
            risk_evaluation_id=evaluation_id,
        )
        session.rollback()
        content, generation_status, model_name = (
            await generate_recovery_report_copy(
                prepared_report,
                ai_client=ai_client,
            )
        )
        report = store_prepared_recovery_report(
            session,
            prepared=prepared_report,
            content=content,
            generation_status=generation_status,
            model_name=model_name,
        )
        report_status = report.generation_status
        session.commit()
    finally:
        await ai_client.aclose()

    print(
        f"[ok] {HIGH_RISK_EMAIL}: 기록 {HISTORY_DAYS}일"
        f"(최근 {DECLINE_DAYS}일 악화), baseline "
        f"{baseline.status.value}(sample_days={baseline.sample_days}), "
        f"위험도 {result.level.value}(score={result.score}), "
        f"회복 리포트 {report_status}"
    )
    return True


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine = create_database_engine(settings.database_url)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    anchor_date = datetime.now(UTC).date()
    print(f"대상 DB: {settings.database_url_for_logging}")
    try:
        with session_factory() as session:
            seed_insufficient_records_user(session, anchor_date=anchor_date)
            seed_normal_pattern_user(session, anchor_date=anchor_date)
            asyncio.run(
                seed_high_risk_user(session, settings, anchor_date=anchor_date)
            )
    finally:
        engine.dispose()
    print("Demo data seeded.")


if __name__ == "__main__":
    main()


__all__ = [
    "DEMO_PASSWORD",
    "HIGH_RISK_EMAIL",
    "INSUFFICIENT_EMAIL",
    "INSUFFICIENT_RECORD_DAYS",
    "NORMAL_EMAIL",
    "main",
    "seed_high_risk_user",
    "seed_insufficient_records_user",
    "seed_normal_pattern_user",
]
