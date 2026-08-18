import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserType


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserTypeUpdate(BaseModel):
    user_type: UserType


class UserNameUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str | None = None
    user_type: UserType | None = None