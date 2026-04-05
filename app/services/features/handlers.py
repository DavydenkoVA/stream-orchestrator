from __future__ import annotations

import logging
import re

from app.config import settings
from app.services.features.base import ChatRequest, FeatureContext, FeatureHandler, FeatureResponse
from app.text_utils import prepare_chat_text

logger = logging.getLogger(__name__)


class DossierFeatureHandler(FeatureHandler):
    route_name = "dossier"

    DOSSIER_PATTERN = re.compile(r"досье\s+на\s+@?([A-Za-z0-9_]+)", flags=re.IGNORECASE)

    def extract_target(self, text: str) -> str | None:
        match = self.DOSSIER_PATTERN.search(text)
        if not match:
            return None
        return match.group(1).strip()

    def matches(self, request: ChatRequest) -> bool:
        return self.extract_target(request.text.strip()) is not None

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:
        dossier_target = self.extract_target(request.text.strip())
        if dossier_target is None:
            return FeatureResponse(reply_text="", route=self.route_name)

        target = request.username if not dossier_target else dossier_target
        normalized_target = target.strip().lstrip("@").lower()

        if normalized_target == settings.bot_username.strip().lstrip("@").lower():
            return FeatureResponse(
                reply_text="На себя досье не веду — конфликт интересов. Kappa",
                route=self.route_name,
            )

        await context.user_memory.refresh_user_memory_if_needed(
            context.db,
            normalized_target,
        )
        context_data = context.dossier.build_context(context.db, normalized_target)
        recent_messages = context_data.get("recent_messages", [])
        memory_items = context_data.get("memory_items", [])

        if len(recent_messages) < 2 and len(memory_items) == 0:
            return FeatureResponse(
                reply_text=f"На @{normalized_target} пока мало данных для нормального досье TPFufun",
                route=self.route_name,
            )

        recent_block = "\n".join(f"- {msg}" for msg in recent_messages[:15]) or "- Нет данных"
        memory_block = (
                "\n".join(
                    f"- type: {item['kind']}; fact: {item['text']}; "
                    f"confidence: {item['confidence']}; evidence: {item['evidence_count']}"
                    for item in memory_items[:10]
                )
                or "- Нет данных"
        )

        try:
            reply = await context.llm.generate_text(
                system_prompt=context.prompts.read("dossier_system.txt"),
                user_prompt=context.prompts.render(
                    "dossier_user_template.txt",
                    username=dossier_target,
                    recent_block=recent_block,
                    memory_block=memory_block,
                ),
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
            )
        except Exception:
            logger.exception("Dossier generation failed")
            reply = f"Не удалось собрать досье на @{normalized_target}"

        return FeatureResponse(
            reply_text=prepare_chat_text(reply, settings.twitch_message_limit),
            route=self.route_name,
        )


class WeeklyMoviesFeatureHandler(FeatureHandler):
    route_name = "weekly_movies"

    TRIGGERS = [
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

    def matches(self, request: ChatRequest) -> bool:
        normalized = request.text.strip().lower()
        return any(trigger in normalized for trigger in self.TRIGGERS)

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:
        weekly_movies_data = context.weekly_movies.read_raw()

        if weekly_movies_data["found"] and weekly_movies_data["content"]:
            file_content = weekly_movies_data["content"]
        else:
            file_content = (
                weekly_movies_data["message"] or "Список фильмов на эту неделю пока пуст."
            )

        try:
            reply = await context.llm.generate_text(
                system_prompt=context.prompts.read("weekly_movies_system.txt"),
                user_prompt=context.prompts.render(
                    "weekly_movies_user_template.txt",
                    user_text=request.text.strip(),
                    file_content=file_content,
                ),
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
            )
        except Exception:
            logger.exception("Weekly movies reply failed")
            reply = "Не удалось прочитать список фильмов"

        return FeatureResponse(
            reply_text=prepare_chat_text(reply, settings.twitch_message_limit),
            route=self.route_name,
        )


class MentionChatFeatureHandler(FeatureHandler):
    route_name = "chat"

    def matches(self, request: ChatRequest) -> bool:
        return request.mentions_bot

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:
        normalized_username = request.username.strip().lstrip("@").lower()

        global_recent = context.chat_memory.recent_messages(
            context.db,
            stream_id=request.stream_id,
            limit=settings.chat_global_context_limit,
        )
        user_recent = context.chat_memory.recent_user_messages(
            context.db,
            stream_id=request.stream_id,
            username=normalized_username,
            limit=settings.chat_user_context_limit,
        )
        dialog_recent = context.chat_memory.recent_dialog_messages(
            context.db,
            stream_id=request.stream_id,
            username=normalized_username,
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

        reply_context_block = "Нет"

        if request.reply_to_text:
            parent_user = request.reply_to_username or "unknown"
            reply_context_block = f"{parent_user}: {request.reply_to_text}"

        system_prompt = context.prompts.read("chat_system.txt")
        user_prompt = context.prompts.render(
            "chat_user_template.txt",
            username=request.username,
            text=request.text.strip(),
            reply_context_block=reply_context_block,
            user_recent_block=user_recent_block,
            global_recent_block=global_recent_block,
            dialog_recent_block=dialog_recent_block,
        )

        try:
            reply = await context.llm.generate_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
            )
        except Exception:
            logger.exception("Chat reply generation failed")
            reply = f"@{request.username}, не удалось получить ответ"

        return FeatureResponse(
            reply_text=prepare_chat_text(reply, settings.twitch_message_limit),
            route=self.route_name,
        )


class IgnoreFeatureHandler(FeatureHandler):
    route_name = "ignored"

    def matches(self, request: ChatRequest) -> bool:
        return True

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:
        return FeatureResponse(reply_text="", route=self.route_name)
