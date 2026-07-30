from __future__ import annotations

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


__all__ = ["get_latest_consent_record"]
