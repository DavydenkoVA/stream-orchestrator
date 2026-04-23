from __future__ import annotations
import logging
import re
import typing
from typing import TYPE_CHECKING  # noqa: COP002

from app.config import settings
from app.observability.trace_helpers import trace_info, trace_success
from app.prompt_store import PromptStore
from app.services.chat_memory import ChatMemoryService
from app.services.dossier import DossierService
from app.services.features import (
    ChatRequest,
    DossierFeatureHandler,
    FeatureContext,
    FeatureSelector,
    IgnoreFeatureHandler,
    MentionChatFeatureHandler,
    WeeklyMoviesFeatureHandler,
)
from app.services.file_readers.weekly_movies import WeeklyMoviesFileService
from app.services.llm_execution_service import LLMExecutionService
from app.services.llm_registry import LLMRegistry
from app.services.provider_state_store import ProviderStateStore
from app.services.style_prompt import StylePromptService
from app.services.style_registry import StyleRegistry
from app.services.user_memory_service import UserMemoryService


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)  # noqa: COP005


class RouterService:  # noqa: COP012
    def __init__(
        self,
        prompt_store: PromptStore | None = None,
        selector: FeatureSelector | None = None,
    ) -> None:
        self.chat_memory = ChatMemoryService()
        self.dossier = DossierService()
        self.weekly_movies = WeeklyMoviesFileService(settings.weekly_movies_file)
        self.prompts = prompt_store or PromptStore()
        self.llm_registry = LLMRegistry()
        self.provider_state_store = ProviderStateStore()
        self.llm_executor = LLMExecutionService(
            llm_registry=self.llm_registry,
            state_store=self.provider_state_store,
        )
        self.user_memory = UserMemoryService(
            llm_registry=self.llm_registry,
            llm_executor=self.llm_executor,
            prompts=self.prompts,
            chat_memory=self.chat_memory,
        )
        self.selector = selector or FeatureSelector(
            [
                DossierFeatureHandler(),
                WeeklyMoviesFeatureHandler(),
                MentionChatFeatureHandler(),
                IgnoreFeatureHandler(),
            ]
        )
        self.style_registry = StyleRegistry()
        self.style_prompt = StylePromptService(self.style_registry)

    def normalize_username(self, username: str) -> str:  # noqa: COP009
        return username.strip().lstrip("@").lower()

    def extract_dossier_target(self, text: str) -> str | None:  # noqa: COP006
        match: typing.Final = re.search(r"досье\s+на\s+@?([A-Za-z0-9_]+)", text, flags=re.IGNORECASE)  # noqa: COP005
        if not match:
            return None
        return match.group(1).strip()

    def is_dossier_request(self, text: str) -> bool:  # noqa: COP006
        return self.extract_dossier_target(text) is not None

    def is_weekly_movies_request(self, text: str) -> bool:  # noqa: COP006
        normalized: typing.Final = text.lower()
        triggers: typing.Final = WeeklyMoviesFeatureHandler.TRIGGERS  # noqa: COP011
        return any(trigger in normalized for trigger in triggers)  # noqa: COP005, COP015

    def ingest_chat_event(  # noqa: COP009, PLR0913
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
    ) -> None:
        normalized_username: typing.Final = self.normalize_username(username)
        normalized_reply_to_username: typing.Final = (
            self.normalize_username(reply_to_username) if reply_to_username else None
        )

        trace_info("chat_message.save.start", "saving chat message", payload={"stream_id": stream_id, "role": role})
        self.chat_memory.save_message(
            db,
            stream_id=stream_id,
            username=normalized_username,
            text=text,
            mentions_bot=mentions_bot,
            role=role,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            reply_to_username=normalized_reply_to_username,
            reply_to_text=reply_to_text,
        )
        db.commit()
        try:
            trace_success("chat_message.save.success", "chat message saved", payload={"stream_id": stream_id})
        except Exception:  # noqa: BLE001
            logger.warning("trace operation failed: chat_message.save.success", exc_info=True)

    async def run_dossier(
        self,
        db: Session,  # noqa: COP006
        *,
        stream_id: str,
        username: str,
        target_username: str,
    ) -> tuple[str, str]:
        request: typing.Final = ChatRequest(  # noqa: COP005
            stream_id=stream_id,
            username=username,
            text=f"досье на @{target_username}",
            mentions_bot=False,
            role="viewer",
        )
        context: typing.Final = FeatureContext(  # noqa: COP005
            db=db,
            llm_registry=self.llm_registry,
            llm_executor=self.llm_executor,
            prompts=self.prompts,
            chat_memory=self.chat_memory,
            dossier=self.dossier,
            weekly_movies=self.weekly_movies,
            user_memory=self.user_memory,
            style_prompt=self.style_prompt,
        )
        handler: typing.Final = DossierFeatureHandler()  # noqa: COP005, COP011
        response: typing.Final = await handler.handle(context, request)
        return response.reply_text, response.route

    async def handle_chat_reply(  # noqa: PLR0913
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
    ) -> tuple[str, str]:
        self.ingest_chat_event(
            db,
            stream_id=stream_id,
            username=username,
            text=text,
            mentions_bot=mentions_bot,
            role=role,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            reply_to_username=reply_to_username,
            reply_to_text=reply_to_text,
        )

        if role == "bot":
            return "", "ignored"

        request: typing.Final = ChatRequest(  # noqa: COP005
            stream_id=stream_id,
            username=username,
            text=text.strip(),
            mentions_bot=mentions_bot,
            role=role,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            reply_to_username=reply_to_username,
            reply_to_text=reply_to_text,
        )

        context: typing.Final = FeatureContext(  # noqa: COP005
            db=db,
            llm_registry=self.llm_registry,
            llm_executor=self.llm_executor,
            prompts=self.prompts,
            chat_memory=self.chat_memory,
            dossier=self.dossier,
            weekly_movies=self.weekly_movies,
            user_memory=self.user_memory,
            style_prompt=self.style_prompt,
        )

        handler: typing.Final = self.selector.select(request)  # noqa: COP005
        trace_success(
            "feature.select.success",
            "feature handler selected",
            payload={"handler": handler.__class__.__name__},
        )
        response: typing.Final = await handler.handle(context, request)
        trace_success("route.result.success", "route produced result", payload={"route": response.route})
        return response.reply_text, response.route
