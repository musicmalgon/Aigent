from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from app.models.user import User


@pytest.fixture
def user_factory(
    db_session: Session,
) -> Callable[[str], User]:
    def create(email: str) -> User:
        user = User(email=email, hashed_password="test-password-hash")
        db_session.add(user)
        db_session.flush()
        return user

    return create


@pytest.fixture
def user(user_factory: Callable[[str], User]) -> User:
    return user_factory("persistence-user@example.com")


@pytest.fixture
def other_user(user_factory: Callable[[str], User]) -> User:
    return user_factory("other-user@example.com")
