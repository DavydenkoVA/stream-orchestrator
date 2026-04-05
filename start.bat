@echo off
setlocal

IF NOT EXIST .venv (
    echo [SETUP] Creating virtual environment...
    uv venv
    IF ERRORLEVEL 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

IF NOT EXIST data\sqlite (
    echo [SETUP] Creating data\sqlite directory...
    mkdir data\sqlite
    IF ERRORLEVEL 1 (
        echo [ERROR] Failed to create data\sqlite directory.
        pause
        exit /b 1
    )
)

echo [SYNC] Installing/updating dependencies...
uv sync
IF ERRORLEVEL 1 (
    echo [ERROR] Dependency sync failed.
    pause
    exit /b 1
)

echo [DB] Applying migrations...
uv run alembic upgrade head
IF ERRORLEVEL 1 (
    echo [ERROR] Database migration failed.
    pause
    exit /b 1
)

echo [RUN] Starting server...
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
IF ERRORLEVEL 1 (
    echo [ERROR] Server failed to start.
    pause
    exit /b 1
)

pause