from __future__ import annotations
from dataclasses import dataclass  # noqa: COP002
from typing import TYPE_CHECKING  # noqa: COP002


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
class ChatRequest:  # noqa: COP012, COP014
    stream_id: str
    username: str
    text: str  # noqa: COP004
    mentions_bot: bool
    role: str = "viewer"  # noqa: COP004
    message_id: str | None = None
    reply_to_message_id: str | None = None
    reply_to_username: str | None = None
    reply_to_text: str | None = None


@dataclass(slots=True)
class FeatureResponse:  # noqa: COP012, COP014
    reply_text: str
    route: str  # noqa: COP004


@dataclass(slots=True)
class FeatureContext:  # noqa: COP012, COP014
    db: Session  # noqa: COP004
    llm_registry: LLMRegistry
    llm_executor: LLMExecutionService
    prompts: PromptStore  # noqa: COP004
    chat_memory: ChatMemoryService
    dossier: DossierService  # noqa: COP004
    weekly_movies: WeeklyMoviesFileService
    user_memory: UserMemoryService
    style_prompt: StylePromptService


class FeatureHandler:  # noqa: COP012
    route_name: str

    def matches(self, request: ChatRequest) -> bool:  # noqa: COP006, COP007, COP009
        raise NotImplementedError

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:  # noqa: COP006, COP007
        raise NotImplementedError
