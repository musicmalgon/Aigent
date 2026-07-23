import uuid
from pydantic import BaseModel, EmailStr
from app.models.user import UserType


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserTypeUpdate(BaseModel):
    user_type: UserType


class UserRead(BaseModel):
    id: uuid.UUID
    email: EmailStr
    user_type: UserType | None = None

    class Config:
        from_attributes = True