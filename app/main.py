from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import inspect

import app.models  # noqa: F401
from app.api.admin_routes import router as admin_router
from app.api.error_handlers import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.api.request_id import generate_request_id, set_request_id
from app.api.routes import router
from app.db import engine
from app.logging_setup import setup_logging
from app.config import settings


setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    inspector = inspect(engine)

    if not inspector.get_table_names():
        raise RuntimeError(
            "Database is not initialized. Run migrations: alembic upgrade head"
        )
    yield


app = FastAPI(title="Stream Orchestrator", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = generate_request_id()
    set_request_id(request, request_id)

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(router)
app.include_router(admin_router)
