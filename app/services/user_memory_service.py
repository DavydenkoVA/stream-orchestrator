from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user_memory import UserMemoryItem
from app.prompt_store import PromptStore
from app.services.chat_memory import ChatMemoryService
from app.services.llm_registry import LLMRegistry

logger = logging.getLogger(__name__)


class UserMemoryService:
    def __init__(
        self,
        *,
        llm_registry: LLMRegistry,
        prompts: PromptStore,
        chat_memory: ChatMemoryService,
    ) -> None:
        self.llm_registry = llm_registry
        self.prompts = prompts
        self.chat_memory = chat_memory

    def count_memory_items(self, db: Session, username: str) -> int:
        stmt = select(UserMemoryItem).where(UserMemoryItem.username == username)
        return len(list(db.scalars(stmt)))

    def get_memory_items(self, db: Session, username: str) -> list[UserMemoryItem]:
        stmt = (
            select(UserMemoryItem)
            .where(UserMemoryItem.username == username)
            .order_by(
                UserMemoryItem.confidence.desc(),
                UserMemoryItem.evidence_count.desc(),
                UserMemoryItem.updated_at.desc(),
                UserMemoryItem.created_at.desc(),
            )
        )
        return list(db.scalars(stmt))

    def should_refresh_user_memory(self, db: Session, username: str) -> tuple[bool, str]:
        memory_items_count = self.count_memory_items(db, username)
        total_user_messages = self.chat_memory.count_user_messages(db, username=username)
        unprocessed_count = self.chat_memory.count_unprocessed_user_messages(db, username=username)

        if memory_items_count == 0 and total_user_messages >= settings.user_memory_bootstrap_message_threshold:
            return True, "bootstrap"

        if memory_items_count > 0 and unprocessed_count >= settings.user_memory_min_unprocessed_messages:
            return True, "refresh"

        return False, "skip"

    def get_messages_for_refresh(self, db: Session, username: str, mode: str):
        if mode == "bootstrap":
            return self.chat_memory.recent_user_messages_for_memory(
                db,
                username=username,
                limit=settings.user_memory_extract_message_limit,
            )

        return self.chat_memory.unprocessed_user_messages_for_memory(
            db,
            username=username,
            limit=settings.user_memory_extract_message_limit,
        )

    async def extract_memory_candidates(self, username: str, messages: list[str]) -> list[dict]:
        if not messages:
            return []

        llm, feature_cfg = self.llm_registry.get_for_feature("user_memory")

        messages_block = "\n".join(f"- {msg}" for msg in messages)

        system_prompt = self.prompts.read("user_memory_system.txt")
        user_prompt = self.prompts.render(
            "user_memory_user_template.txt",
            username=username,
            messages_block=messages_block,
        )

        raw = await llm.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=feature_cfg.temperature,
            max_output_tokens=feature_cfg.max_output_tokens,
        )

        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("User memory extraction returned invalid JSON: %s", raw)
            return []

        if not isinstance(parsed, list):
            return []

        valid_kinds = {"preference", "pattern", "topic", "joke", "quote", "meta"}
        candidates: list[dict] = []

        for item in parsed:
            if not isinstance(item, dict):
                continue

            kind = str(item.get("kind", "")).strip()
            text = str(item.get("text", "")).strip()
            evidence_count = item.get("evidence_count", 1)
            confidence = item.get("confidence", 0.0)

            if kind not in valid_kinds:
                continue

            if not text:
                continue

            try:
                evidence_count = int(evidence_count)
            except Exception:
                evidence_count = 1

            try:
                confidence = float(confidence)
            except Exception:
                confidence = 0.0

            if confidence < settings.user_memory_min_confidence:
                continue

            if evidence_count < 1:
                evidence_count = 1

            candidates.append(
                {
                    "kind": kind,
                    "text": text,
                    "evidence_count": evidence_count,
                    "confidence": confidence,
                }
            )

        return candidates

    def merge_memory_candidates(self, db: Session, username: str, candidates: list[dict]) -> None:
        if not candidates:
            return

        existing_items = self.get_memory_items(db, username)
        existing_map = {
            (item.kind.strip().lower(), item.text.strip().lower()): item
            for item in existing_items
        }

        now = datetime.utcnow()

        for candidate in candidates:
            key = (
                candidate["kind"].strip().lower(),
                candidate["text"].strip().lower(),
            )

            existing = existing_map.get(key)
            if existing is not None:
                existing.evidence_count += candidate["evidence_count"]
                existing.confidence = max(existing.confidence, candidate["confidence"])
                existing.updated_at = now
            else:
                new_item = UserMemoryItem(
                    username=username,
                    kind=candidate["kind"],
                    text=candidate["text"],
                    evidence_count=candidate["evidence_count"],
                    confidence=candidate["confidence"],
                    created_at=now,
                    updated_at=now,
                )
                db.add(new_item)

        db.commit()

    def trim_user_memory(self, db: Session, username: str) -> None:
        items = self.get_memory_items(db, username)

        if len(items) <= settings.user_memory_max_items_per_user:
            return

        to_delete = items[settings.user_memory_max_items_per_user :]
        ids_to_delete = [item.id for item in to_delete]

        if not ids_to_delete:
            return

        stmt = delete(UserMemoryItem).where(UserMemoryItem.id.in_(ids_to_delete))
        db.execute(stmt)
        db.commit()

    async def refresh_user_memory_if_needed(self, db: Session, username: str) -> bool:
        should_refresh, mode = self.should_refresh_user_memory(db, username)
        if not should_refresh:
            return False

        messages = self.get_messages_for_refresh(db, username, mode)
        if not messages:
            return False

        message_ids = [m.id for m in messages]
        message_texts = [m.text for m in messages]

        candidates = await self.extract_memory_candidates(username, message_texts)
        self.merge_memory_candidates(db, username, candidates)
        self.trim_user_memory(db, username)
        self.chat_memory.mark_messages_memory_processed(db, message_ids=message_ids)

        logger.info(
            "User memory refreshed: username=%s mode=%s messages=%s candidates=%s",
            username,
            mode,
            len(messages),
            len(candidates),
        )
        return True