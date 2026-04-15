from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect

import app.models as app_models
from app.api.admin_routes import router as admin_router
from app.api.error_handlers import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.api.request_id import generate_request_id, set_request_id
from app.api.routes import router
from app.config import settings
from app.db import engine
from app.logging_setup import setup_logging
from app.observability.request_context import clear_current_request_id, set_current_request_id


setup_logging(settings.log_level)
_loaded_models = app_models


@asynccontextmanager
async def lifespan(_: FastAPI):
    inspector = inspect(engine)

    if not inspector.get_table_names():
        raise RuntimeError("Database is not initialized. Run migrations: alembic upgrade head")
    yield


app = FastAPI(title="Stream Orchestrator", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = generate_request_id()
    set_request_id(request, request_id)
    set_current_request_id(request_id)

    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        clear_current_request_id()


app.add_exception_handler(
    RequestValidationError,
    cast(Callable[[Request, Exception], Response | Awaitable[Response]], validation_exception_handler),
)
app.add_exception_handler(
    HTTPException,
    cast(Callable[[Request, Exception], Response | Awaitable[Response]], http_exception_handler),
)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(router)
app.include_router(admin_router)
