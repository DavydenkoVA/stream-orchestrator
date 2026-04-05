from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage


class ChatMemoryService:
    def save_message(
            self,
            db: Session,
            *,
            stream_id: str,
            username: str,
            text: str,
            mentions_bot: bool,
            role: str = "viewer",
            message_id: str | None = None,
            reply_to_message_id: str | None = None,
            reply_to_username: str | None = None,
            reply_to_text: str | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
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
        db.commit()
        db.refresh(message)
        return message

    def recent_messages(
        self,
        db: Session,
        *,
        stream_id: str,
        limit: int = 20,
    ) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.stream_id == stream_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(list(db.scalars(stmt))))

    def recent_user_messages(
        self,
        db: Session,
        *,
        stream_id: str,
        username: str,
        limit: int = 8,
    ) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.stream_id == stream_id,
                ChatMessage.username == username,
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(list(db.scalars(stmt))))

    def recent_dialog_messages(
        self,
        db: Session,
        *,
        stream_id: str,
        username: str,
        limit: int = 12,
    ) -> list[ChatMessage]:
        from sqlalchemy import or_

        stmt = (
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
        db: Session,
        *,
        username: str,
    ) -> int:
        stmt = select(func.count(ChatMessage.id)).where(
            ChatMessage.username == username,
            ChatMessage.role == "viewer",
        )
        return int(db.scalar(stmt) or 0)

    def count_unprocessed_user_messages(
        self,
        db: Session,
        *,
        username: str,
    ) -> int:
        stmt = select(func.count(ChatMessage.id)).where(
            ChatMessage.username == username,
            ChatMessage.role == "viewer",
            ChatMessage.is_memory_processed.is_(False),
        )
        return int(db.scalar(stmt) or 0)

    def recent_user_messages_for_memory(
        self,
        db: Session,
        *,
        username: str,
        limit: int,
    ) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.username == username,
                ChatMessage.role == "viewer",
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(list(db.scalars(stmt))))

    def unprocessed_user_messages_for_memory(
        self,
        db: Session,
        *,
        username: str,
        limit: int,
    ) -> list[ChatMessage]:
        stmt = (
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

    def mark_messages_memory_processed(
        self,
        db: Session,
        *,
        message_ids: list[int],
    ) -> None:
        if not message_ids:
            return

        stmt = (
            update(ChatMessage)
            .where(ChatMessage.id.in_(message_ids))
            .values(is_memory_processed=True)
        )
        db.execute(stmt)
        db.commit()