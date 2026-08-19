from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.orm import Session

from app.models.consent import ConsentRecord, ConsentType


def get_latest_consent_record(
    db: Session,
    *,
    user_id: str,
    consent_type: ConsentType,
) -> ConsentRecord | None:
    return (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.user_id == user_id,
            ConsentRecord.consent_type == consent_type,
        )
        .order_by(ConsentRecord.created_at.desc())
        .first()
    )


def delete_all_consent_records_for_user(
    session: Session,
    *,
    user_id: str,
) -> int:
    # 원래는 감사 추적을 위해 계정 삭제 시에도 보존했지만(#133), 계정 자체를
    # 지우는 진짜 삭제로 바뀌면서 재로그인이 불가능해져 추적 보존의 의미가
    # 없어짐 -- 개인정보의 일부로 보고 같이 지운다.
    result = cast(
        "CursorResult[Any]",
        session.execute(
            delete(ConsentRecord).where(ConsentRecord.user_id == user_id)
        ),
    )
    session.flush()
    return result.rowcount


__all__ = ["delete_all_consent_records_for_user", "get_latest_consent_record"]
