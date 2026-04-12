from fastapi import FastAPI

from app.api.routes import router
from app.config import settings
from app.db import Base, engine
from app.logging_setup import setup_logging
import app.models  # noqa: F401
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

setup_logging(settings.log_level)

app = FastAPI(title="Stream Orchestrator")

@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


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