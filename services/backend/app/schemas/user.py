import re
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserType

SPECIAL_CHARS = r"""!@#$%^&*()_+\-=\[\]{};':"\\|,.<>/?"""


def _check_password_strength(v: str) -> str:
    if len(v) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")
    if not re.search(r"[A-Za-z]", v):
        raise ValueError("비밀번호에 영문자를 포함해야 합니다.")
    if not re.search(r"[0-9]", v):
        raise ValueError("비밀번호에 숫자를 포함해야 합니다.")
    if not re.search(f"[{re.escape(SPECIAL_CHARS)}]", v):
        raise ValueError("비밀번호에 특수문자를 포함해야 합니다.")
    return v


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _check_password_strength(v)


class UserTypeUpdate(BaseModel):
    user_type: UserType


class UserNameUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _check_password_strength(v)


class AccountDataDeleteRequest(BaseModel):
    current_password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str | None = None
    user_type: UserType | None = None


class AccountDataDeletionSummaryRead(BaseModel):
    # 서비스 계층이 돌려주는 dataclass를 그대로 응답으로 검증하기 위한 설정.
    model_config = ConfigDict(from_attributes=True)

    recovery_reports_deleted: int
    risk_evaluations_deleted: int
    baselines_deleted: int
    emotion_analyses_deleted: int
    daily_records_deleted: int