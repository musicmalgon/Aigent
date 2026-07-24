import uuid

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import UserType


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserTypeUpdate(BaseModel):
    user_type: UserType


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    user_type: UserType | None = None
