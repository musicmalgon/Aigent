from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.consent import ConsentRecord, ConsentStatus, ConsentType
from app.models.user import User
from app.repositories.consent import get_latest_consent_record
from app.schemas.consent import ConsentGrantRequest, ConsentRecordRead

router = APIRouter(prefix="/api/v1/consents", tags=["consents"])

NO_ACTIVE_CONSENT_DETAIL = "해당 동의 항목에 대한 활성 동의가 없습니다"
NOT_WITHDRAWABLE_DETAIL = "이 동의 항목은 철회할 수 없습니다"

# 서비스 이용약관/개인정보 수집은 서비스 이용 자체의 전제조건이라 언제든
# 껐다 켤 수 있는 다른 동의(건강 데이터 활용, 마음 기록 분석, 외부 연동)와
# 달리 철회를 허용하지 않는다. 프론트 UI에서만 막으면 API를 직접 호출해
# 우회할 수 있으므로 여기서도 같은 규칙을 강제한다.
NON_WITHDRAWABLE_CONSENT_TYPES = frozenset(
    {ConsentType.TERMS_OF_SERVICE, ConsentType.PRIVACY_POLICY}
)


@router.post(
    "",
    response_model=ConsentRecordRead,
    status_code=status.HTTP_201_CREATED,
)
def grant_consent(
    payload: ConsentGrantRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConsentRecord:
    record = ConsentRecord(
        user_id=current_user.id,
        consent_type=payload.consent_type,
        status=ConsentStatus.GRANTED,
        granted_at=datetime.now(UTC),
        withdrawn_at=None,
        source=payload.source,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("", response_model=list[ConsentRecordRead])
def read_current_consents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConsentRecord]:
    rows = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.user_id == current_user.id)
        .order_by(ConsentRecord.created_at.desc())
        .all()
    )
    # 이력 전체가 아니라 항목별 현재 상태만 — 내림차순이므로 처음 만난 행이 최신이다.
    # 레거시 Column 스타일이라 row.consent_type의 정적 타입이 Column이므로 키는 Any.
    current: dict[Any, ConsentRecord] = {}
    for row in rows:
        current.setdefault(row.consent_type, row)
    return list(current.values())


@router.delete(
    "/{consent_type}",
    response_model=ConsentRecordRead,
    status_code=status.HTTP_201_CREATED,
)
def withdraw_consent(
    consent_type: ConsentType,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConsentRecord:
    if consent_type in NON_WITHDRAWABLE_CONSENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=NOT_WITHDRAWABLE_DETAIL,
        )

    latest = get_latest_consent_record(
        db,
        user_id=current_user.id,
        consent_type=consent_type,
    )
    if latest is None or latest.status == ConsentStatus.WITHDRAWN:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NO_ACTIVE_CONSENT_DETAIL,
        )

    # 철회도 삭제가 아니라 새 이력 행 — 원 동의 시각과 출처를 그대로 이어받는다
    record = ConsentRecord(
        user_id=current_user.id,
        consent_type=consent_type,
        status=ConsentStatus.WITHDRAWN,
        granted_at=latest.granted_at,
        withdrawn_at=datetime.now(UTC),
        source=latest.source,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


__all__ = ["router"]
