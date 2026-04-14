@echo off
echo [DB] Stamping existing database to current head...
uv run alembic stamp head
IF ERRORLEVEL 1 (
    echo [ERROR] Alembic stamp failed.
    pause
    exit /b 1
)
echo [OK] Existing database is now aligned with Alembic.
pause