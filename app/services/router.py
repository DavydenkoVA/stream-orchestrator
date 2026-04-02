import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.llm.base import LLMProvider
from app.integrations.llm.factory import build_llm_provider
from app.prompt_store import PromptStore
from app.services.chat_memory import ChatMemoryService
from app.services.dossier import DossierService
from app.services.file_readers.weekly_movies import WeeklyMoviesFileService
from app.text_utils import prepare_chat_text

logger = logging.getLogger(__name__)


class RouterService:
    def __init__(
        self,
        llm: LLMProvider | None = None,
        prompt_store: PromptStore | None = None,
    ) -> None:
        self.chat_memory = ChatMemoryService()
        self.dossier = DossierService()
        self.weekly_movies = WeeklyMoviesFileService(settings.weekly_movies_file)
        self.llm = llm or build_llm_provider()
        self.prompts = prompt_store or PromptStore()

    def ingest_chat_event(
        self,
        db: Session,
        *,
        stream_id: str,
        username: str,
        text: str,
        mentions_bot: bool,
        role: str = "viewer",
    ) -> None:
        self.chat_memory.save_message(
            db,
            stream_id=stream_id,
            username=username,
            text=text,
            mentions_bot=mentions_bot,
            role=role,
        )

    def is_weekly_movies_request(self, text: str) -> bool:
        normalized = text.lower()

        triggers = [
            "что смотрим",
            "что будем смотреть",
            "какие фильмы",
            "что на этой неделе",
            "что в списке",
            "что смотрим в воскресенье",
            "фильмы недели",
            "что по фильмам",
            "что у нас по фильмам",
            "что смотрим на этой неделе",
            "что на этой неделе смотрим",
            "какие фильмы на неделе",
        ]

        return any(trigger in normalized for trigger in triggers)

    def build_chat_context(
        self,
        db: Session,
        *,
        stream_id: str,
        username: str,
        text: str,
    ) -> dict:
        global_recent = self.chat_memory.recent_messages(
            db,
            stream_id=stream_id,
            limit=settings.chat_global_context_limit,
        )
        user_recent = self.chat_memory.recent_user_messages(
            db,
            stream_id=stream_id,
            username=username,
            limit=settings.chat_user_context_limit,
        )
        dialog_recent = self.chat_memory.recent_dialog_messages(
            db,
            stream_id=stream_id,
            username=username,
            limit=settings.chat_dialog_context_limit,
        )

        global_recent_block = "\n".join(
            f"{m.username} [{m.role}]: {m.text}" for m in global_recent
        ) or "Нет данных."

        user_recent_block = "\n".join(
            f"{m.username} [{m.role}]: {m.text}" for m in user_recent
        ) or "Нет данных."

        dialog_recent_block = "\n".join(
            f"{m.username} [{m.role}]: {m.text}" for m in dialog_recent
        ) or "Нет данных."

        system_prompt = self.prompts.read("chat_system.txt")
        user_prompt = self.prompts.render(
            "chat_user_template.txt",
            username=username,
            text=text.strip(),
            user_recent_block=user_recent_block,
            global_recent_block=global_recent_block,
            dialog_recent_block=dialog_recent_block,
        )

        return {
            "global_recent": [f"{m.username} [{m.role}]: {m.text}" for m in global_recent],
            "user_recent": [f"{m.username} [{m.role}]: {m.text}" for m in user_recent],
            "dialog_recent": [f"{m.username} [{m.role}]: {m.text}" for m in dialog_recent],
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }

    async def handle_weekly_movies_reply(self, user_text: str) -> str:
        weekly_movies_data = self.weekly_movies.read_raw()

        if weekly_movies_data["found"] and weekly_movies_data["content"]:
            file_content = weekly_movies_data["content"]
        else:
            file_content = weekly_movies_data["message"] or "Список фильмов на эту неделю пока пуст."

        reply = await self.llm.generate_text(
            system_prompt=self.prompts.read("weekly_movies_system.txt"),
            user_prompt=self.prompts.render(
                "weekly_movies_user_template.txt",
                user_text=user_text,
                file_content=file_content,
            ),
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_output_tokens,
        )

        return prepare_chat_text(reply, settings.twitch_message_limit)

    async def handle_chat_reply(
        self,
        db: Session,
        *,
        stream_id: str,
        username: str,
        text: str,
        mentions_bot: bool,
        role: str = "viewer",
    ) -> tuple[str, str]:
        self.ingest_chat_event(
            db,
            stream_id=stream_id,
            username=username,
            text=text,
            mentions_bot=mentions_bot,
            role=role,
        )

        normalized_text = text.strip()

        if normalized_text.lower().startswith("досье на @"):
            target = normalized_text.split("@", 1)[1].strip()
            context = self.dossier.build_context(db, target)

            recent_block = "\n".join(
                f"- {msg}" for msg in context.get("recent_messages", [])[:15]
            ) or "- Нет данных"

            memory_block = (
                "\n".join(
                    f"- [{item['kind']}] {item['text']} "
                    f"(confidence={item['confidence']}, evidence={item['evidence_count']})"
                    for item in context.get("memory_items", [])[:10]
                )
                or "- Нет данных"
            )

            try:
                reply = await self.llm.generate_text(
                    system_prompt=self.prompts.read("dossier_system.txt"),
                    user_prompt=self.prompts.render(
                        "dossier_user_template.txt",
                        username=target,
                        recent_block=recent_block,
                        memory_block=memory_block,
                    ),
                    temperature=settings.llm_temperature,
                    max_output_tokens=settings.llm_max_output_tokens,
                )
            except Exception as e:
                logger.exception("Dossier generation failed")
                reply = f"Не удалось собрать досье на @{target}"

            reply = prepare_chat_text(reply, settings.twitch_message_limit)
            return reply, "dossier"

        if self.is_weekly_movies_request(normalized_text):
            try:
                reply = await self.handle_weekly_movies_reply(normalized_text)
            except Exception as e:
                logger.exception("Weekly movies reply failed")
                reply = f"Не удалось прочитать список фильмов"

            return reply, "weekly_movies"

        if not mentions_bot:
            return "", "ignored"

        context = self.build_chat_context(
            db,
            stream_id=stream_id,
            username=username,
            text=normalized_text,
        )

        try:
            reply = await self.llm.generate_text(
                system_prompt=context["system_prompt"],
                user_prompt=context["user_prompt"],
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
            )
        except Exception as e:
            logger.exception("Chat reply generation failed")
            reply = f"@{username}, не удалось получить ответ"

        reply = prepare_chat_text(reply, settings.twitch_message_limit)
        return reply, "chat"