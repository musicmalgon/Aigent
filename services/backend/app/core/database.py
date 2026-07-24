from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str) -> Engine:
    connect_args = (
        {"check_same_thread": False}
        if make_url(database_url).get_backend_name() == "sqlite"
        else {}
    )
    return create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


engine = create_database_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = [
    "Base",
    "SessionLocal",
    "create_database_engine",
    "engine",
    "get_db",
]
