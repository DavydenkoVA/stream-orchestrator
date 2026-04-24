from pathlib import Path

from sqlalchemy import text

from app.db import _build_engine


SQLITE_BUSY_TIMEOUT_MS = 30000


def test_build_engine_applies_sqlite_timeout_and_pragmas(tmp_path: Path) -> None:
    database_engine = _build_engine(f"sqlite:///{tmp_path / 'sqlite_mitigation.db'}")
    try:
        with database_engine.connect() as connection:
            busy_timeout = connection.execute(text("PRAGMA busy_timeout;")).scalar_one()
            journal_mode = connection.execute(text("PRAGMA journal_mode;")).scalar_one()

        assert busy_timeout == SQLITE_BUSY_TIMEOUT_MS
        assert str(journal_mode).lower() == "wal"
    finally:
        database_engine.dispose()
