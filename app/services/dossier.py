from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage
from app.models.user_memory import UserMemoryItem


class DossierService:
    def build_context(self, db: Session, username: str) -> dict:
        messages = list(
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.username == username)
                .order_by(ChatMessage.created_at.desc())
                .limit(30)
            )
        )
        memory_items = list(
            db.scalars(
                select(UserMemoryItem)
                .where(UserMemoryItem.username == username)
                .order_by(UserMemoryItem.confidence.desc(), UserMemoryItem.created_at.desc())
                .limit(20)
            )
        )

        return {
            "username": username,
            "recent_messages": [m.text for m in messages],
            "memory_items": [
                {
                    "kind": item.kind,
                    "text": item.text,
                    "confidence": item.confidence,
                    "evidence_count": item.evidence_count,
                }
                for item in memory_items
            ],
        }
