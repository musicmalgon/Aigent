"""Add the uppercase ConsentType labels SQLAlchemy actually persists.

20260821_0012의 Postgres 분기가 틀렸다: ConsentType 컬럼은
Column(Enum(ConsentType))로, values_callable을 지정하지 않아서
SQLAlchemy가 파이썬 enum 멤버의 .value(소문자, 예: "terms_of_service")가
아니라 .name(대문자, 예: "TERMS_OF_SERVICE")를 DB에 쓴다 -- 실제로 원래
enum 타입도 대문자로 만들어졌었다(f4c75e0aa428: sa.Enum('HEALTH_DATA',
'EMOTION_DIARY', ...)). 0012는 이걸 놓치고 소문자 값(never used, 죽은
라벨)만 추가해서, 실제로 필요한 대문자 값이 하나도 추가되지 않은 채
남아있었다. 그 결과 이용약관/개인정보/외부연동 동의를 저장하려 할 때마다
"invalid input value for enum consenttype" 500 에러가 났다(#197 배포
직후 실사용자 보고로 발견).

0012의 SQLite 분기는 원래도 대문자로 맞게 짜여 있었어서(테스트가
Base.metadata.create_all()로 매번 새로 만드는 스키마라 이 문제 자체가
재현되지 않음) 이 마이그레이션은 Postgres 분기만 다룬다.

Revision ID: 20260821_0013
Revises: 20260821_0012
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0013"
down_revision: str | None = "20260821_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VALUES = ("TERMS_OF_SERVICE", "PRIVACY_POLICY", "EXTERNAL_INTEGRATION")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for value in NEW_VALUES:
                op.execute(f"ALTER TYPE consenttype ADD VALUE IF NOT EXISTS '{value}'")
    # SQLite는 0012에서 이미 대문자 값 기준으로 컬럼 타입 메타데이터가
    # 맞춰져 있어서 여기서 할 일이 없다.


def downgrade() -> None:
    # Postgres 네이티브 ENUM은 값을 제거하려면 타입을 통째로 재생성해야
    # 하고, 그 값을 참조하는 행이 이미 있으면 그 행부터 정리해야 해서
    # 안전하게 자동화하기 어렵다. 필요해지면 그때 수동으로 처리한다.
    pass
