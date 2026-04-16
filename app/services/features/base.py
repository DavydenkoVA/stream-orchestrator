from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.prompt_store import PromptStore
    from app.services.chat_memory import ChatMemoryService
    from app.services.dossier import DossierService
    from app.services.file_readers.weekly_movies import WeeklyMoviesFileService
    from app.services.llm_execution_service import LLMExecutionService
    from app.services.llm_registry import LLMRegistry
    from app.services.style_prompt import StylePromptService
    from app.services.user_memory_service import UserMemoryService


@dataclass(slots=True)
class ChatRequest:
    stream_id: str
    username: str
    text: str
    mentions_bot: bool
    role: str = "viewer"
    message_id: str | None = None
    reply_to_message_id: str | None = None
    reply_to_username: str | None = None
    reply_to_text: str | None = None


@dataclass(slots=True)
class FeatureResponse:
    reply_text: str
    route: str


@dataclass(slots=True)
class FeatureContext:
    db: Session
    llm_registry: LLMRegistry
    llm_executor: LLMExecutionService
    prompts: PromptStore
    chat_memory: ChatMemoryService
    dossier: DossierService
    weekly_movies: WeeklyMoviesFileService
    user_memory: UserMemoryService
    style_prompt: StylePromptService


class FeatureHandler:
    route_name: str

    def matches(self, request: ChatRequest) -> bool:
        raise NotImplementedError

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:
        raise NotImplementedError
