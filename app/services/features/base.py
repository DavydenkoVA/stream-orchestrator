from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.integrations.llm.base import LLMProvider
from app.prompt_store import PromptStore
from app.services.chat_memory import ChatMemoryService
from app.services.dossier import DossierService
from app.services.file_readers.weekly_movies import WeeklyMoviesFileService
from app.services.user_memory_service import UserMemoryService


@dataclass(slots=True)
class ChatRequest:
    stream_id: str
    username: str
    text: str
    mentions_bot: bool
    role: str = "viewer"


@dataclass(slots=True)
class FeatureResponse:
    reply_text: str
    route: str


@dataclass(slots=True)
class FeatureContext:
    db: Session
    llm: LLMProvider
    prompts: PromptStore
    chat_memory: ChatMemoryService
    dossier: DossierService
    weekly_movies: WeeklyMoviesFileService
    user_memory: UserMemoryService


class FeatureHandler:
    route_name: str

    def matches(self, request: ChatRequest) -> bool:
        raise NotImplementedError

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:
        raise NotImplementedError