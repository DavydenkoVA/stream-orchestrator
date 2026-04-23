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


LOGGER_INSTANCE = logging.getLogger(__name__)


VALID_MEMORY_KINDS: typing.Final[frozenset[str]] = frozenset(
    {"preference", "pattern", "topic", "joke", "quote", "meta"}
)


@typing.final
class MemoryCandidate(pydantic.BaseModel):
    kind: typing.Literal["preference", "pattern", "topic", "joke", "quote", "meta"]
    text: str = pydantic.Field(min_length=1)
    evidence_count: int = pydantic.Field(ge=1)
    confidence: float


@typing.final
class MemoryCandidateList(pydantic.BaseModel):
    root: list[MemoryCandidate]


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class MemoryExtractionResult:
    ok: bool  # noqa: COP004
    status: str  # noqa: COP004
    candidates: list[MemoryCandidate]
    error_code: str | None
    error_details: str | None = None


@typing.final
class UserMemoryService:
    def __init__(
        self,
        *,
        llm_registry: LLMRegistry,
        llm_executor: LLMExecutionService,
        prompts: PromptStore,  # noqa: COP006
        chat_memory: ChatMemoryService,
    ) -> None:
        self.llm_registry = llm_registry
        self.llm_executor = llm_executor
        self.prompts = prompts
        self.chat_memory = chat_memory

    def count_memory_items(self, database_session: Session, username: str) -> int:
        return len(list(database_session.scalars(select(UserMemoryItem).where(UserMemoryItem.username == username))))

    def list_memory_items(self, database_session: Session, username: str) -> list[UserMemoryItem]:
        select_statement = (
            select(UserMemoryItem)
            .where(UserMemoryItem.username == username)
            .order_by(
                UserMemoryItem.confidence.desc(),
                UserMemoryItem.evidence_count.desc(),
                UserMemoryItem.updated_at.desc(),
                UserMemoryItem.created_at.desc(),
            )
        )
        return list(database_session.scalars(select_statement))

    def get_memory_items(self, database_session: Session, username: str) -> list[UserMemoryItem]:  # noqa: COP009
        return self.list_memory_items(database_session, username)

    def should_refresh_user_memory(self, database_session: Session, username: str) -> tuple[bool, str]:
        memory_items_count = self.count_memory_items(database_session, username)
        total_user_messages = self.chat_memory.count_user_messages(database_session, username=username)
        unprocessed_messages_count = self.chat_memory.count_unprocessed_user_messages(
            database_session,
            username=username,
        )

        if memory_items_count == 0 and total_user_messages >= settings.user_memory_bootstrap_message_threshold:
            return True, "bootstrap"
        if memory_items_count > 0 and unprocessed_messages_count >= settings.user_memory_min_unprocessed_messages:
            return True, "refresh"
        return False, "skip"

    def select_messages_for_refresh(  # noqa: COP009
        self,
        database_session: Session,
        username: str,
        refresh_mode: str,
    ) -> list[ChatMessage]:
        if refresh_mode == "bootstrap":
            return self.chat_memory.recent_user_messages_for_memory(
                database_session,
                username=username,
                limit=settings.user_memory_extract_message_limit,
            )
        return self.chat_memory.unprocessed_user_messages_for_memory(
            database_session,
            username=username,
            limit=settings.user_memory_extract_message_limit,
        )

    async def extract_memory_candidates(
        self,
        database_session: Session,
        username: str,
        message_texts: list[str],
    ) -> MemoryExtractionResult:
        if not message_texts:
            return MemoryExtractionResult(ok=True, status="success_empty", candidates=[], error_code=None)

        provider_pool, provider_feature_settings = self.llm_registry.get_for_feature("user_memory")
        messages_block = "\n".join(f"- {one_message_text}" for one_message_text in message_texts)

        system_prompt = self.prompts.read("user_memory_system.txt")
        user_prompt = self.prompts.render(
            "user_memory_user_template.txt",
            username=username,
            messages_block=messages_block,
        )

        try:
            raw_response_text = await self.llm_executor.generate_text_with_pool(
                db=database_session,
                pool=provider_pool,
                feature_settings=provider_feature_settings,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as extraction_error:  # noqa: BLE001
            return MemoryExtractionResult(
                ok=False,
                status="failed_provider",
                candidates=[],
                error_code="memory_provider_error",
                error_details=str(extraction_error),
            )

        try:
            parsed_response = json.loads(raw_response_text)
        except json.JSONDecodeError as parsing_error:
            LOGGER_INSTANCE.warning(
                "User memory extraction returned invalid JSON: username=%s raw=%s",
                username,
                raw_response_text[:500],
            )
            return MemoryExtractionResult(
                ok=False,
                status="failed_parse",
                candidates=[],
                error_code="memory_parse_error",
                error_details=str(parsing_error),
            )

        try:
            validated_candidates = MemoryCandidateList.model_validate({"root": parsed_response})
        except pydantic.ValidationError as validation_error:
            return MemoryExtractionResult(
                ok=False,
                status="failed_schema",
                candidates=[],
                error_code="memory_schema_error",
                error_details=str(validation_error),
            )

        filtered_candidates = [
            one_candidate
            for one_candidate in validated_candidates.root
            if one_candidate.kind in VALID_MEMORY_KINDS
            and one_candidate.text.strip()
            and one_candidate.evidence_count >= 1
            and one_candidate.confidence >= settings.user_memory_min_confidence
        ]
        if not filtered_candidates:
            return MemoryExtractionResult(ok=True, status="success_empty", candidates=[], error_code=None)

        return MemoryExtractionResult(ok=True, status="success", candidates=filtered_candidates, error_code=None)

    def merge_memory_candidates(
        self,
        database_session: Session,
        username: str,
        candidate_items: list[MemoryCandidate],
    ) -> None:
        if not candidate_items:
            return

        existing_memory_items = self.list_memory_items(database_session, username)
        existing_memory_by_key = {
            (one_item.kind.strip().lower(), one_item.text.strip().lower()): one_item
            for one_item in existing_memory_items
        }

        current_timestamp = datetime.datetime.now(datetime.UTC)
        for one_candidate in candidate_items:
            candidate_key = (
                one_candidate.kind.strip().lower(),
                one_candidate.text.strip().lower(),
            )
            existing_memory_item = existing_memory_by_key.get(candidate_key)
            if existing_memory_item is not None:
                existing_memory_item.evidence_count += one_candidate.evidence_count
                existing_memory_item.confidence = max(existing_memory_item.confidence, one_candidate.confidence)
                existing_memory_item.updated_at = current_timestamp
                continue

            database_session.add(
                UserMemoryItem(
                    username=username,
                    kind=one_candidate.kind,
                    text=one_candidate.text,
                    evidence_count=one_candidate.evidence_count,
                    confidence=one_candidate.confidence,
                    created_at=current_timestamp,
                    updated_at=current_timestamp,
                )
            )

        database_session.flush()

    def trim_user_memory(self, database_session: Session, username: str) -> None:  # noqa: COP009
        memory_items = self.list_memory_items(database_session, username)
        if len(memory_items) <= settings.user_memory_max_items_per_user:
            return

        memory_item_ids_to_delete = [
            one_item.id for one_item in memory_items[settings.user_memory_max_items_per_user :]
        ]
        if not memory_item_ids_to_delete:
            return

        database_session.execute(delete(UserMemoryItem).where(UserMemoryItem.id.in_(memory_item_ids_to_delete)))
        database_session.flush()

    async def refresh_user_memory_if_needed(self, database_session: Session, username: str) -> bool:  # noqa: COP009
        should_refresh, refresh_mode = self.should_refresh_user_memory(database_session, username)
        if not should_refresh:
            app.observability.trace_helpers.trace_info(
                "user_memory.refresh.skipped",
                "user memory refresh skipped",
                payload={"username": username},
            )
            return False

        selected_messages = self.select_messages_for_refresh(database_session, username, refresh_mode)
        if not selected_messages:
            app.observability.trace_helpers.trace_info(
                "user_memory.refresh.skipped",
                "user memory refresh skipped: no messages",
                payload={"username": username},
            )
            return False

        selected_message_ids = [one_message.id for one_message in selected_messages]
        selected_message_texts = [one_message.text for one_message in selected_messages]
        app.observability.trace_helpers.trace_info(
            "user_memory.refresh.start",
            "user memory refresh started",
            payload={
                "username": username,
                "mode": refresh_mode,
                "messages_count": len(selected_message_texts),
            },
        )

        try:
            extraction_result = await self.extract_memory_candidates(
                database_session,
                username,
                selected_message_texts,
            )
            self.chat_memory.mark_messages_memory_extraction_attempted(
                database_session,
                message_ids=selected_message_ids,
                error_code=extraction_result.error_code,
            )
            if not extraction_result.ok:
                app.observability.trace_helpers.trace_failure(
                    "user_memory.extract.failed",
                    "memory extraction failed",
                    error_code=extraction_result.error_code or "memory_extraction_failed",
                    payload={
                        "status": extraction_result.status,
                        "messages_count": len(selected_message_ids),
                    },
                )
                database_session.commit()
                LOGGER_INSTANCE.warning(
                    "User memory extraction failed: username=%s mode=%s status=%s error_code=%s messages=%s",
                    username,
                    refresh_mode,
                    extraction_result.status,
                    extraction_result.error_code,
                    len(selected_messages),
                )
                return False

            app.observability.trace_helpers.trace_success(
                "user_memory.extract.success",
                "memory extraction finished",
                payload={
                    "status": extraction_result.status,
                    "candidates_count": len(extraction_result.candidates),
                },
            )
            self.merge_memory_candidates(database_session, username, extraction_result.candidates)
            app.observability.trace_helpers.trace_success("user_memory.merge.success", "memory merge completed")
            self.trim_user_memory(database_session, username)
            app.observability.trace_helpers.trace_success("user_memory.trim.success", "memory trim completed")
            self.chat_memory.mark_messages_memory_processed(database_session, message_ids=selected_message_ids)
            app.observability.trace_helpers.trace_success(
                "user_memory.mark_processed.success",
                "marked messages as processed",
                payload={"messages_count": len(selected_message_ids)},
            )
            database_session.commit()
            app.observability.trace_helpers.trace_success(
                "user_memory.refresh.success",
                "user memory refresh committed",
                payload={"username": username},
            )
        except Exception:
            database_session.rollback()
            app.observability.trace_helpers.trace_failure(
                "user_memory.refresh.failed",
                "user memory refresh failed",
                error_code="internal_error",
            )
            raise

        if extraction_result.status == "success_empty":
            LOGGER_INSTANCE.info(
                "User memory extraction succeeded with no candidates: username=%s mode=%s messages=%s",
                username,
                refresh_mode,
                len(selected_messages),
            )
        else:
            LOGGER_INSTANCE.info(
                "User memory refreshed: username=%s mode=%s messages=%s candidates=%s",
                username,
                refresh_mode,
                len(selected_messages),
                len(extraction_result.candidates),
            )
        return True
