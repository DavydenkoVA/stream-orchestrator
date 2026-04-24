import typing
from datetime import UTC, datetime  # noqa: COP002
from typing import TYPE_CHECKING, cast  # noqa: COP002

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage


if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult


@typing.final
class ChatMemoryService:
    def save_message(  # noqa: PLR0913
        self,
        db: Session,  # noqa: COP006
        *,
        stream_id: str,
        username: str,
        text: str,  # noqa: COP006
        mentions_bot: bool,
        role: str = "viewer",  # noqa: COP006
        message_id: str | None = None,
        reply_to_message_id: str | None = None,
        reply_to_username: str | None = None,
        reply_to_text: str | None = None,
    ) -> ChatMessage:
        message: typing.Final = ChatMessage(  # noqa: COP005
            stream_id=stream_id,
            username=username,
            role=role,
            text=text,
            mentions_bot=mentions_bot,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            reply_to_username=reply_to_username,
            reply_to_text=reply_to_text,
        )
        db.add(message)
        db.flush()
        return message

    def recent_messages(  # noqa: COP009
        self,
        db: Session,  # noqa: COP006
        *,
        stream_id: str,
        limit: int = 20,  # noqa: COP006
    ) -> list[ChatMessage]:
        stmt: typing.Final = (  # noqa: COP005
            select(ChatMessage)
            .where(ChatMessage.stream_id == stream_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(list(db.scalars(stmt))))

    def recent_user_messages(  # noqa: COP009
        self,
        db: Session,  # noqa: COP006
        *,
        stream_id: str,
        username: str,
        limit: int = 8,  # noqa: COP006
    ) -> list[ChatMessage]:
        stmt: typing.Final = (  # noqa: COP005
            select(ChatMessage)
            .where(
                ChatMessage.stream_id == stream_id,
                ChatMessage.username == username,
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(list(db.scalars(stmt))))

    def recent_dialog_messages(  # noqa: COP009
        self,
        db: Session,  # noqa: COP006
        *,
        stream_id: str,
        username: str,
        limit: int = 12,  # noqa: COP006
    ) -> list[ChatMessage]:
        stmt: typing.Final = (  # noqa: COP005
            select(ChatMessage)
            .where(
                ChatMessage.stream_id == stream_id,
                or_(
                    ChatMessage.username == username,
                    ChatMessage.role == "bot",
                ),
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(list(db.scalars(stmt))))

    def count_user_messages(
        self,
        db: Session,  # noqa: COP006
        *,
        username: str,
    ) -> int:
        stmt: typing.Final = select(func.count(ChatMessage.id)).where(  # noqa: COP005
            ChatMessage.username == username,
            ChatMessage.role == "viewer",
        )
        return int(db.scalar(stmt) or 0)

    def count_unprocessed_user_messages(
        self,
        db: Session,  # noqa: COP006
        *,
        username: str,
    ) -> int:
        stmt: typing.Final = select(func.count(ChatMessage.id)).where(  # noqa: COP005
            ChatMessage.username == username,
            ChatMessage.role == "viewer",
            ChatMessage.is_memory_processed.is_(False),
        )
        return int(db.scalar(stmt) or 0)

    def recent_user_messages_for_memory(  # noqa: COP009
        self,
        db: Session,  # noqa: COP006
        *,
        username: str,
        limit: int,  # noqa: COP006
    ) -> list[ChatMessage]:
        stmt: typing.Final = (  # noqa: COP005
            select(ChatMessage)
            .where(
                ChatMessage.username == username,
                ChatMessage.role == "viewer",
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(list(db.scalars(stmt))))

    def unprocessed_user_messages_for_memory(  # noqa: COP009
        self,
        db: Session,  # noqa: COP006
        *,
        username: str,
        limit: int,  # noqa: COP006
    ) -> list[ChatMessage]:
        stmt: typing.Final = (  # noqa: COP005
            select(ChatMessage)
            .where(
                ChatMessage.username == username,
                ChatMessage.role == "viewer",
                ChatMessage.is_memory_processed.is_(False),
            )
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .limit(limit)
        )
        return list(db.scalars(stmt))

    def mark_messages_memory_processed(  # noqa: COP009
        self,
        db: Session,  # noqa: COP006
        *,
        message_ids: list[int],
    ) -> None:
        if not message_ids:
            return

        stmt: typing.Final = (  # noqa: COP005
            update(ChatMessage)
            .where(ChatMessage.id.in_(message_ids))
            .values(
                is_memory_processed=True,
                memory_last_error_code=None,
            )
        )
        db.execute(stmt)

    def mark_messages_memory_extraction_attempted(  # noqa: COP009
        self,
        db: Session,  # noqa: COP006
        *,
        message_ids: list[int],
        error_code: str | None,
    ) -> None:
        if not message_ids:
            return

        stmt: typing.Final = (  # noqa: COP005
            update(ChatMessage)
            .where(
                ChatMessage.id.in_(message_ids),
                ChatMessage.is_memory_processed.is_(False),
            )
            .values(
                memory_process_attempts=ChatMessage.memory_process_attempts + 1,
                memory_last_attempt_at=datetime.now(UTC),
                memory_last_error_code=error_code,
            )
        )
        db.execute(stmt)

    def delete_stream_messages(
        self,
        db: Session,  # noqa: COP006
        *,
        stream_id: str,
    ) -> int:
        stmt: typing.Final = delete(ChatMessage).where(ChatMessage.stream_id == stream_id)  # noqa: COP005, COP011
        result: typing.Final = db.execute(stmt)  # noqa: COP005, COP011
        return int(cast("CursorResult[object]", result).rowcount or 0)
