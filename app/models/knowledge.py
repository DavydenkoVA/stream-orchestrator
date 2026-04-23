from datetime import UTC, datetime  # noqa: COP002

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KnowledgeItem(Base):  # noqa: COP012
    __tablename__ = "knowledge_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # noqa: COP004
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)  # noqa: COP004
    content: Mapped[str] = mapped_column(Text)  # noqa: COP004
    tags: Mapped[str] = mapped_column(String(512), default="")  # noqa: COP004
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        index=True,
    )
