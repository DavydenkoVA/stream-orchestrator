from datetime import UTC, datetime  # noqa: COP002

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StreamSummary(Base):  # noqa: COP012
    __tablename__ = "stream_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # noqa: COP004
    stream_id: Mapped[str] = mapped_column(String(128), index=True)
    window_label: Mapped[str] = mapped_column(String(64), index=True)
    summary_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        index=True,
    )
