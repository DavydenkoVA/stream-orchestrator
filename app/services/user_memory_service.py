from __future__ import annotations
import dataclasses
import datetime
import json
import logging
import typing

import pydantic
from sqlalchemy import delete, select

import app.observability.trace_helpers
from app.config import settings
from app.models.user_memory import UserMemoryItem


if typing.TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.chat import ChatMessage
    from app.prompt_store import PromptStore
    from app.services.chat_memory import ChatMemoryService
    from app.services.llm_execution_service import LLMExecutionService
    from app.services.llm_registry import LLMRegistry


logger = logging.getLogger(__name__)


VALID_MEMORY_KINDS: typing.Final[frozenset[str]] = frozenset(
    {"preference", "pattern", "topic", "joke", "quote", "meta"}
)


class MemoryCandidate(pydantic.BaseModel):
    kind: typing.Literal["preference", "pattern", "topic", "joke", "quote", "meta"]
    text: str = pydantic.Field(min_length=1)
    evidence_count: int = pydantic.Field(ge=1)
    confidence: float


class MemoryCandidateList(pydantic.BaseModel):
    root: list[MemoryCandidate]


@dataclasses.dataclass(slots=True)
class MemoryExtractionResult:
    ok: bool
    status: str
    candidates: list[MemoryCandidate]
    error_code: str | None
    error_details: str | None = None


class UserMemoryService:
    def __init__(
        self,
        *,
        llm_registry: LLMRegistry,
        llm_executor: LLMExecutionService,
        prompts: PromptStore,
        chat_memory: ChatMemoryService,
    ) -> None:
        self.llm_registry = llm_registry
        self.llm_executor = llm_executor
        self.prompts = prompts
        self.chat_memory = chat_memory

    def count_memory_items(self, db: Session, username: str) -> int:
        stmt: typing.Final = select(UserMemoryItem).where(UserMemoryItem.username == username)
        return len(list(db.scalars(stmt)))

    def get_memory_items(self, db: Session, username: str) -> list[UserMemoryItem]:
        stmt: typing.Final = (
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
        memory_items_count: typing.Final = self.count_memory_items(db, username)
        total_user_messages: typing.Final = self.chat_memory.count_user_messages(db, username=username)
        unprocessed_count: typing.Final = self.chat_memory.count_unprocessed_user_messages(db, username=username)

        if memory_items_count == 0 and total_user_messages >= settings.user_memory_bootstrap_message_threshold:
            return True, "bootstrap"

        if memory_items_count > 0 and unprocessed_count >= settings.user_memory_min_unprocessed_messages:
            return True, "refresh"

        return False, "skip"

    def select_messages_for_refresh(self, db: Session, username: str, mode: str) -> list[ChatMessage]:
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

    async def extract_memory_candidates(
        self,
        db: Session,
        username: str,
        messages: list[str],
    ) -> MemoryExtractionResult:
        if not messages:
            return MemoryExtractionResult(
                ok=True,
                status="success_empty",
                candidates=[],
                error_code=None,
            )

        pool, feature_cfg = self.llm_registry.get_for_feature("user_memory")

        messages_block: typing.Final = "\n".join(f"- {msg}" for msg in messages)

        system_prompt: typing.Final = self.prompts.read("user_memory_system.txt")
        user_prompt: typing.Final = self.prompts.render(
            "user_memory_user_template.txt",
            username=username,
            messages_block=messages_block,
        )

        try:
            raw: typing.Final = await self.llm_executor.generate_text_with_pool(
                db=db,
                pool=pool,
                feature_settings=feature_cfg,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:  # noqa: BLE001
            return MemoryExtractionResult(
                ok=False,
                status="failed_provider",
                candidates=[],
                error_code="memory_provider_error",
                error_details=str(exc),
            )

        try:
            parsed_response: typing.Final = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "User memory extraction returned invalid JSON: username=%s raw=%s",
                username,
                raw[:500],
            )
            return MemoryExtractionResult(
                ok=False,
                status="failed_parse",
                candidates=[],
                error_code="memory_parse_error",
                error_details=str(exc),
            )

        try:
            validated: typing.Final = MemoryCandidateList.model_validate({"root": parsed_response})
        except pydantic.ValidationError as exc:
            return MemoryExtractionResult(
                ok=False,
                status="failed_schema",
                candidates=[],
                error_code="memory_schema_error",
                error_details=str(exc),
            )

        candidates: typing.Final = [
            item
            for item in validated.root
            if item.kind in VALID_MEMORY_KINDS
            and item.text.strip()
            and item.evidence_count >= 1
            and item.confidence >= settings.user_memory_min_confidence
        ]

        if not candidates:
            return MemoryExtractionResult(
                ok=True,
                status="success_empty",
                candidates=[],
                error_code=None,
            )

        return MemoryExtractionResult(
            ok=True,
            status="success",
            candidates=candidates,
            error_code=None,
        )

    def merge_memory_candidates(
        self,
        db: Session,
        username: str,
        candidates: list[MemoryCandidate],
    ) -> None:
        if not candidates:
            return

        existing_items: typing.Final = self.get_memory_items(db, username)
        existing_map: typing.Final = {
            (item.kind.strip().lower(), item.text.strip().lower()): item for item in existing_items
        }

        now: typing.Final = datetime.datetime.now(datetime.UTC)

        for candidate in candidates:
            key = (
                candidate.kind.strip().lower(),
                candidate.text.strip().lower(),
            )

            existing = existing_map.get(key)
            if existing is not None:
                existing.evidence_count += candidate.evidence_count
                existing.confidence = max(existing.confidence, candidate.confidence)
                existing.updated_at = now
            else:
                new_item = UserMemoryItem(
                    username=username,
                    kind=candidate.kind,
                    text=candidate.text,
                    evidence_count=candidate.evidence_count,
                    confidence=candidate.confidence,
                    created_at=now,
                    updated_at=now,
                )
                db.add(new_item)

        db.flush()

    def trim_user_memory(self, db: Session, username: str) -> None:
        items: typing.Final = self.get_memory_items(db, username)

        if len(items) <= settings.user_memory_max_items_per_user:
            return

        to_delete: typing.Final = items[settings.user_memory_max_items_per_user :]
        ids_to_delete: typing.Final = [item.id for item in to_delete]

        if not ids_to_delete:
            return

        stmt: typing.Final = delete(UserMemoryItem).where(UserMemoryItem.id.in_(ids_to_delete))
        db.execute(stmt)
        db.flush()

    async def refresh_user_memory_if_needed(self, db: Session, username: str) -> bool:
        should_refresh, mode = self.should_refresh_user_memory(db, username)
        if not should_refresh:
            app.observability.trace_helpers.trace_info(
                "user_memory.refresh.skipped",
                "user memory refresh skipped",
                payload={"username": username},
            )
            return False

        messages: typing.Final = self.select_messages_for_refresh(db, username, mode)
        if not messages:
            app.observability.trace_helpers.trace_info(
                "user_memory.refresh.skipped",
                "user memory refresh skipped: no messages",
                payload={"username": username},
            )
            return False

        message_ids: typing.Final = [m.id for m in messages]
        message_texts: typing.Final = [m.text for m in messages]
        app.observability.trace_helpers.trace_info(
            "user_memory.refresh.start",
            "user memory refresh started",
            payload={"username": username, "mode": mode, "messages_count": len(message_texts)},
        )

        try:
            extraction: typing.Final = await self.extract_memory_candidates(db, username, message_texts)
            self.chat_memory.mark_messages_memory_extraction_attempted(
                db,
                message_ids=message_ids,
                error_code=extraction.error_code,
            )
            if not extraction.ok:
                app.observability.trace_helpers.trace_failure(
                    "user_memory.extract.failed",
                    "memory extraction failed",
                    error_code=extraction.error_code or "memory_extraction_failed",
                    payload={"status": extraction.status, "messages_count": len(message_ids)},
                )
                db.commit()
                logger.warning(
                    "User memory extraction failed: username=%s mode=%s status=%s error_code=%s messages=%s",
                    username,
                    mode,
                    extraction.status,
                    extraction.error_code,
                    len(messages),
                )
                return False

            app.observability.trace_helpers.trace_success(
                "user_memory.extract.success",
                "memory extraction finished",
                payload={"status": extraction.status, "candidates_count": len(extraction.candidates)},
            )
            self.merge_memory_candidates(db, username, extraction.candidates)
            app.observability.trace_helpers.trace_success("user_memory.merge.success", "memory merge completed")
            self.trim_user_memory(db, username)
            app.observability.trace_helpers.trace_success("user_memory.trim.success", "memory trim completed")
            self.chat_memory.mark_messages_memory_processed(db, message_ids=message_ids)
            app.observability.trace_helpers.trace_success(
                "user_memory.mark_processed.success",
                "marked messages as processed",
                payload={"messages_count": len(message_ids)},
            )
            db.commit()
            app.observability.trace_helpers.trace_success(
                "user_memory.refresh.success", "user memory refresh committed", payload={"username": username}
            )
        except Exception:
            db.rollback()
            app.observability.trace_helpers.trace_failure(
                "user_memory.refresh.failed",
                "user memory refresh failed",
                error_code="internal_error",
            )
            raise

        if extraction.status == "success_empty":
            logger.info(
                "User memory extraction succeeded with no candidates: username=%s mode=%s messages=%s",
                username,
                mode,
                len(messages),
            )
        else:
            logger.info(
                "User memory refreshed: username=%s mode=%s messages=%s candidates=%s",
                username,
                mode,
                len(messages),
                len(extraction.candidates),
            )
        return True
