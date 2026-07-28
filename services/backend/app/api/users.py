from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import PasswordUpdate, UserNameUpdate, UserRead, UserTypeUpdate

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
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="현재 비밀번호가 일치하지 않습니다",
        )
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()