from sqlalchemy import or_, select
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
    ) -> ChatMessage:
        message = ChatMessage(
            stream_id=stream_id,
            username=username,
            role=role,
            text=text,
            mentions_bot=mentions_bot,
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