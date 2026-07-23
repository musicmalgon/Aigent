from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserRead, UserTypeUpdate

router = APIRouter()


@router.get("/users/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/users/me/type", response_model=UserRead)
def update_user_type(
    payload: UserTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.user_type = payload.user_type
    db.commit()
    db.refresh(current_user)
    return current_user