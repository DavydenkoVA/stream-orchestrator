from datetime import UTC, datetime  # noqa: COP002

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ChatMessage(Base):  # noqa: COP012
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # noqa: COP004
    stream_id: Mapped[str] = mapped_column(String(128), index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer", index=True)  # noqa: COP004
    text: Mapped[str] = mapped_column(Text)  # noqa: COP004
    mentions_bot: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    message_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    reply_to_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reply_to_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_memory_processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    memory_process_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    memory_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    memory_last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        index=True,
    )
