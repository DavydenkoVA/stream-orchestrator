import typing
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):  # noqa: COP008, COP012
    pass


def _is_sqlite_database_url(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "sqlite"


def set_sqlite_connection_pragmas(sqlalchemy_engine: Engine) -> None:
    @event.listens_for(sqlalchemy_engine, "connect")
    def _set_sqlite_pragmas(database_connection: typing.Any, _connection_record: typing.Any) -> None:  # noqa: ANN401
        sqlite_cursor = database_connection.cursor()
        try:
            sqlite_cursor.execute("PRAGMA journal_mode=WAL;")
            sqlite_cursor.execute("PRAGMA busy_timeout=30000;")
        finally:
            sqlite_cursor.close()


def _build_engine(database_url: str) -> Engine:
    if not _is_sqlite_database_url(database_url):
        return create_engine(database_url, future=True)

    sqlite_engine = create_engine(database_url, future=True, connect_args={"timeout": 30})
    set_sqlite_connection_pragmas(sqlite_engine)
    return sqlite_engine


engine = _build_engine(settings.database_url)  # noqa: COP005
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:  # noqa: COP007
    db: typing.Final = SessionLocal()  # noqa: COP005
    try:
        yield db
    finally:
        db.close()
