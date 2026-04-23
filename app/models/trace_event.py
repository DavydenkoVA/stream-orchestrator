from __future__ import annotations
from datetime import UTC, datetime  # noqa: COP002

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TraceEvent(Base):  # noqa: COP012
    __tablename__ = "trace_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # noqa: COP004
    trace_run_id: Mapped[int] = mapped_column(ForeignKey("trace_runs.id"), index=True)
    seq_no: Mapped[int] = mapped_column(Integer)  # noqa: COP004
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), index=True)
    step: Mapped[str] = mapped_column(String(128), index=True)  # noqa: COP004
    status: Mapped[str] = mapped_column(String(16), index=True)  # noqa: COP004
    level: Mapped[str] = mapped_column(String(16), index=True)  # noqa: COP004
    message: Mapped[str] = mapped_column(Text)  # noqa: COP004
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
