"""Expand ConsentType to cover all 5 onboarding consent items.

예전엔 health_data/emotion_diary 2개만 실제로 저장되고, 온보딩 동의 화면의
나머지 3개 항목(이용약관, 개인정보 수집, 외부 서비스 연동)은 화면 체크박스
상태로만 관리돼서 서버에 전혀 남지 않았다. 그 결과 동의내역 화면이 사용자의
실제 선택과 무관하게 이 3개를 항상 "가입 시 동의"라고 표시했다(#H1).

Revision ID: 20260821_0012
Revises: 20260821_0011
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0012"
down_revision: str | None = "20260821_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VALUES = ("terms_of_service", "privacy_policy", "external_integration")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # consent_records.consent_type은 app/models/consent.py의 ConsentType이
        # Enum(native_enum=True)(기본값)라 Postgres에선 진짜 네이티브 ENUM
        # 타입(consenttype)이다. 값을 추가하려면 ALTER TYPE ... ADD VALUE가
        # 필요하고, 이건 PG 12+에서도 트랜잭션 밖에서 실행해야 안전하다
        # (같은 트랜잭션에서 방금 추가한 값을 바로 쓰면 실패하는 버전이 있음).
        with op.get_context().autocommit_block():
            for value in NEW_VALUES:
                op.execute(f"ALTER TYPE consenttype ADD VALUE IF NOT EXISTS '{value}'")
    else:
        # SQLite(테스트 환경) 등 네이티브 enum이 없는 dialect에서는
        # native_enum=True가 그냥 무제약 VARCHAR로 내려가서(CHECK 제약 없음)
        # 값 자체는 이미 뭐든 통과했지만, 최초 마이그레이션이 2개 값 기준으로
        # 구운 컬럼 타입 선언(VARCHAR 길이 등 메타데이터)이 남아 있어서 모델만
        # 넓히면 alembic autogenerate가 "타입이 다르다"고 오탐한다. 컬럼 타입
        # 선언을 5개 값 기준으로 다시 맞춰서 메타데이터를 모델과 일치시킨다.
        with op.batch_alter_table("consent_records") as batch_op:
            batch_op.alter_column(
                "consent_type",
                existing_type=sa.Enum("HEALTH_DATA", "EMOTION_DIARY", name="consenttype"),
                type_=sa.Enum(
                    "TERMS_OF_SERVICE",
                    "PRIVACY_POLICY",
                    "HEALTH_DATA",
                    "EMOTION_DIARY",
                    "EXTERNAL_INTEGRATION",
                    name="consenttype",
                ),
                existing_nullable=False,
            )


def downgrade() -> None:
    # Postgres 네이티브 ENUM에서 값을 제거하려면 타입을 통째로 재생성해야
    # 하고, 그 값을 참조하는 행이 이미 있으면 그 행부터 정리해야 해서
    # 안전하게 자동화하기 어렵다. 필요해지면 그때 수동으로 처리한다.
    pass
