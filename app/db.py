import typing
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):  # noqa: COP008, COP012
    pass


engine = create_engine(settings.database_url, future=True)  # noqa: COP005
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:  # noqa: COP007
    db: typing.Final = SessionLocal()  # noqa: COP005
    try:
        yield db
    finally:
        db.close()
