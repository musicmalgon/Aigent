"""Widen ConsentType with terms_of_service/privacy_policy/external_integration.

Revision ID: 20260821_0012
Revises: 20260821_0011
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260821_0012"
down_revision: str | None = "20260821_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_VALUES = ("HEALTH_DATA", "EMOTION_DIARY")
_NEW_VALUES = ("TERMS_OF_SERVICE", "PRIVACY_POLICY", "EXTERNAL_INTEGRATION")


def _assert_downgrade_is_lossless() -> None:
    if context.is_offline_mode():
        return
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT id FROM consent_records "
                "WHERE consent_type IN "
                "('TERMS_OF_SERVICE', 'PRIVACY_POLICY', 'EXTERNAL_INTEGRATION') "
                "LIMIT 1"
            )
        )
        .first()
    )
    if row is not None:
        raise RuntimeError(
            "Cannot downgrade 20260821_0012: consent_records contains rows "
            "using the new consent types. Resolve those rows explicitly "
            "before retrying; the downgrade did not modify them."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # sa.Enum(ConsentType)는 Postgres에서 진짜 네이티브 ENUM 타입을
        # 만든다(SQLite처럼 CHECK 제약으로 흉내내지 않음) -- 그래서 값을
        # 늘리려면 ALTER TYPE ... ADD VALUE가 필요하다. IF NOT EXISTS로
        # 재실행에도 안전하게 둔다.
        for value in _NEW_VALUES:
            op.execute(f"ALTER TYPE consenttype ADD VALUE IF NOT EXISTS '{value}'")
    else:
        with op.batch_alter_table("consent_records") as batch_op:
            batch_op.alter_column(
                "consent_type",
                existing_type=sa.Enum(*_OLD_VALUES, name="consenttype"),
                type_=sa.Enum(*_OLD_VALUES, *_NEW_VALUES, name="consenttype"),
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Postgres는 ALTER TYPE ... DROP VALUE를 지원하지 않는다(타입
        # 전체를 새로 만들어 옮겨야 함) -- 이 마이그레이션의 downgrade는
        # SQLite(개발/테스트)만 지원한다.
        raise NotImplementedError(
            "Downgrading 20260821_0012 on PostgreSQL is not supported -- "
            "Postgres cannot narrow an existing enum type in place."
        )

    _assert_downgrade_is_lossless()
    with op.batch_alter_table("consent_records") as batch_op:
        batch_op.alter_column(
            "consent_type",
            existing_type=sa.Enum(*_OLD_VALUES, *_NEW_VALUES, name="consenttype"),
            type_=sa.Enum(*_OLD_VALUES, name="consenttype"),
            existing_nullable=False,
        )
