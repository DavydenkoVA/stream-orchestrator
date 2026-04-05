@echo off

IF NOT EXIST .venv (
    echo [SETUP] Creating virtual environment...
    uv venv
)

echo [SYNC] Installing/updating dependencies...
uv sync
uv run alembic upgrade head

echo [RUN] Starting server...
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

pause