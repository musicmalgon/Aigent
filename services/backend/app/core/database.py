from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str) -> Engine:
    is_sqlite = make_url(database_url).get_backend_name() == "sqlite"
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    database_engine = create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )
    if is_sqlite:

        @event.listens_for(database_engine, "connect")
        def enable_sqlite_foreign_keys(
            dbapi_connection: object,
            connection_record: object,
        ) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return database_engine


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
