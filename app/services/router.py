from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.config import settings
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
from app.services.llm_registry import LLMRegistry
from app.services.user_memory_service import UserMemoryService
from app.services.style_prompt import StylePromptService
from app.services.style_registry import StyleRegistry
from app.services.llm_execution_service import LLMExecutionService
from app.services.provider_state_store import ProviderStateStore
from app.observability.trace_helpers import trace_info, trace_success


class RouterService:
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

    def normalize_username(self, username: str) -> str:
        return username.strip().lstrip("@").lower()

    def extract_dossier_target(self, text: str) -> str | None:
        match = re.search(r"досье\s+на\s+@?([A-Za-z0-9_]+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip()

    def is_dossier_request(self, text: str) -> bool:
        return self.extract_dossier_target(text) is not None

    def is_weekly_movies_request(self, text: str) -> bool:
        normalized = text.lower()
        triggers = WeeklyMoviesFeatureHandler.TRIGGERS
        return any(trigger in normalized for trigger in triggers)

    def ingest_chat_event(
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
    ) -> None:
        normalized_username = self.normalize_username(username)
        normalized_reply_to_username = (
            self.normalize_username(reply_to_username)
            if reply_to_username
            else None
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
        trace_success("chat_message.save.success", "chat message saved", payload={"stream_id": stream_id})

    async def handle_chat_reply(
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

        request = ChatRequest(
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

        context = FeatureContext(
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

        handler = self.selector.select(request)
        trace_success(
            "feature.select.success",
            "feature handler selected",
            payload={"handler": handler.__class__.__name__},
        )
        response = await handler.handle(context, request)
        trace_success("route.result.success", "route produced result", payload={"route": response.route})
        return response.reply_text, response.route
