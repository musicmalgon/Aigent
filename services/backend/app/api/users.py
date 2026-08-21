from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import (
    AccountDataDeleteRequest,
    AccountDataDeletionSummaryRead,
    PasswordUpdate,
    UserNameUpdate,
    UserRead,
    UserTypeUpdate,
)
from app.services.account_data import (
    AccountDataDeletionSummary,
    delete_all_account_data,
)

router = APIRouter()


@router.get("/users/me", response_model=UserRead)
def read_current_user(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


@router.patch("/users/me/type", response_model=UserRead)
def update_user_type(
    payload: UserTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    current_user.user_type = payload.user_type
    db.commit()
    db.refresh(current_user)
    return current_user


@router.patch("/users/me/name", response_model=UserRead)
def update_user_name(
    payload: UserNameUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    current_user.name = payload.name
    db.commit()
    db.refresh(current_user)
    return current_user


@router.patch("/users/me/password", status_code=status.HTTP_204_NO_CONTENT)
def update_user_password(
    payload: PasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if current_user.hashed_password is None:
        # 구글 로그인 전용 계정은 애초에 비밀번호가 없다. verify_password에
        # None을 그대로 넘기면 passlib이 TypeError를 던져 500으로 깨졌고,
        # 프론트는 JSON 파싱 실패로 "요청 실패: 500"만 보여줬다(#H5).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="구글 계정으로 가입해 비밀번호가 없는 계정이라 비밀번호를 변경할 수 없습니다.",
        )
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="현재 비밀번호가 일치하지 않습니다",
        )
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()


@router.delete("/users/me/data", response_model=AccountDataDeletionSummaryRead)
def delete_account_data(
    payload: AccountDataDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountDataDeletionSummary:
    # 되돌릴 수 없는 삭제라 비밀번호 변경과 같은 재확인 관문을 둔다 -- 다만
    # 구글 로그인 전용 계정은 애초에 비밀번호가 없어(hashed_password is None)
    # verify_password가 500으로 깨졌다(#H5). 이 계정은 재확인 수단이 비밀번호
    # 밖에 없는 게 아니라 아예 없으므로, 이미 검증된 JWT(get_current_user)
    # 자체를 재확인으로 인정하고 비밀번호 검증만 건너뛴다.
    if current_user.hashed_password is not None and not verify_password(
        payload.current_password, current_user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="현재 비밀번호가 일치하지 않습니다",
        )
    summary = delete_all_account_data(db, user=current_user)
    db.commit()
    return summary