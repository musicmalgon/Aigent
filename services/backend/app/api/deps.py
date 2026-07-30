from collections.abc import Callable
from typing import cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.clients.ai import AIServiceClient
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.consent import ConsentStatus, ConsentType
from app.models.user import User
from app.repositories.consent import get_latest_consent_record

bearer_scheme = HTTPBearer(auto_error=False)


def get_ai_service_client(request: Request) -> AIServiceClient:
    ai_client = getattr(request.app.state, "ai_service_client", None)
    if ai_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Emotion analysis service is unavailable.",
        )
    return cast(AIServiceClient, ai_client)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    return user


def require_consent(consent_type: ConsentType) -> Callable[..., User]:
    """해당 동의 항목이 현재 부여 상태일 때만 통과시키는 의존성을 만든다.

    쓰기 엔드포인트에만 건다. 조회/삭제는 동의와 무관하게 열려 있어야 한다
    (삭제는 사용자가 자기 데이터 삭제권을 행사하는 통로다).
    """

    def _dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        record = get_latest_consent_record(
            db,
            user_id=current_user.id,
            consent_type=consent_type,
        )
        # 이력이 없거나 최신 행이 철회면 모두 미동의 — 철회 행도 남아 있기 때문에
        # "행 존재"가 아니라 최신 행의 status로 판정해야 한다.
        if record is None or record.status != ConsentStatus.GRANTED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{consent_type.value} 동의가 필요합니다",
            )
        return current_user

    return _dependency
