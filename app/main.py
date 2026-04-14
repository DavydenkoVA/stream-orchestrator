from contextlib import asynccontextmanager
import logging

from app.api.admin_routes import router as admin_router
from app.api.routes import router
from app.config import settings
from app.logging_setup import setup_logging
from app.db import engine
from sqlalchemy import inspect
import app.models  # noqa: F401
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = await request.body()
    logger.error("422 validation error on %s", request.url.path)
    logger.error("Request body: %s", body.decode("utf-8", errors="ignore"))
    logger.error("Validation errors: %s", exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


app.include_router(router)
app.include_router(admin_router)
