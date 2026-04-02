from fastapi import FastAPI

from app.api.routes import router
from app.config import settings
from app.db import Base, engine
from app.logging_setup import setup_logging
import app.models  # noqa: F401

setup_logging(settings.log_level)

app = FastAPI(title="Stream Orchestrator")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


app.include_router(router)