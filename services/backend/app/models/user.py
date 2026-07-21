import enum
import uuid
from sqlalchemy import Column, String, DateTime, Enum
from sqlalchemy.sql import func
from app.core.database import Base


class UserType(str, enum.Enum):
    UNIVERSITY_STUDENT = "university_student"
    EARLY_CAREER = "early_career"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    user_type = Column(Enum(UserType), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())