from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(128), index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer", index=True)
    text: Mapped[str] = mapped_column(Text)
    mentions_bot: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    message_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    reply_to_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reply_to_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_memory_processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)