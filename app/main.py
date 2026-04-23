import typing
from collections.abc import AsyncIterator, Awaitable, Callable
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
    handle_http_exception,
    handle_unhandled_exception,
    handle_validation_exception,
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
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    inspector: typing.Final = inspect(engine)

    if not inspector.get_table_names():
        raise RuntimeError("Database is not initialized. Run migrations: alembic upgrade head")
    yield


app = FastAPI(title="Stream Orchestrator", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    request_id: typing.Final = generate_request_id()
    set_request_id(request, request_id)
    set_current_request_id(request_id)

    try:
        response: typing.Final = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        clear_current_request_id()


app.add_exception_handler(
    RequestValidationError,
    cast("Callable[[Request, Exception], Response | Awaitable[Response]]", handle_validation_exception),
)
app.add_exception_handler(
    HTTPException,
    cast("Callable[[Request, Exception], Response | Awaitable[Response]]", handle_http_exception),
)
app.add_exception_handler(Exception, handle_unhandled_exception)

app.include_router(router)
app.include_router(admin_router)
