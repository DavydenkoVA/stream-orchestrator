from __future__ import annotations
import logging
import re
import typing
from typing import ClassVar, cast

from app.config import settings
from app.services.features.base import ChatRequest, FeatureContext, FeatureHandler, FeatureResponse
from app.text_utils import prepare_chat_text


logger = logging.getLogger(__name__)
MIN_RECENT_MESSAGES_FOR_DOSSIER = 2


@typing.final
class DossierFeatureHandler(FeatureHandler):
    route_name = "dossier"

    DOSSIER_PATTERN = re.compile(r"досье\s+на\s+@?([A-Za-z0-9_]+)", flags=re.IGNORECASE)

    def resolve_dossier_target(self, text: str) -> str | None:
        match: typing.Final = self.DOSSIER_PATTERN.search(text)
        if not match:
            return None
        return match.group(1).strip()

    def matches(self, request: ChatRequest) -> bool:
        return self.resolve_dossier_target(request.text.strip()) is not None

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:
        dossier_target: typing.Final = self.resolve_dossier_target(request.text.strip())
        if dossier_target is None:
            return FeatureResponse(reply_text="", route=self.route_name)

        target: typing.Final = dossier_target or request.username
        normalized_target: typing.Final = target.strip().lstrip("@").lower()

        if normalized_target == settings.bot_username.strip().lstrip("@").lower():
            return FeatureResponse(
                reply_text="На себя досье не веду — конфликт интересов. Kappa",  # noqa: RUF001
                route=self.route_name,
            )

        await context.user_memory.refresh_user_memory_if_needed(
            context.db,
            normalized_target,
        )
        context_data: typing.Final = context.dossier.build_context(context.db, normalized_target)
        recent_messages: typing.Final = cast("list[str]", context_data.get("recent_messages", []))
        memory_items: typing.Final = cast("list[dict[str, object]]", context_data.get("memory_items", []))

        if len(recent_messages) < MIN_RECENT_MESSAGES_FOR_DOSSIER and len(memory_items) == 0:
            return FeatureResponse(
                reply_text=f"На @{normalized_target} пока мало данных для нормального досье TPFufun",  # noqa: RUF001
                route=self.route_name,
            )

        recent_block: typing.Final = "\n".join(f"- {msg}" for msg in recent_messages[:15]) or "- Нет данных"
        memory_block: typing.Final = (
            "\n".join(
                f"- type: {item['kind']}; fact: {item['text']}; "
                f"confidence: {item['confidence']}; evidence: {item['evidence_count']}"
                for item in memory_items[:10]
            )
            or "- Нет данных"
        )

        pool, feature_cfg = context.llm_registry.get_for_feature("dossier")
        base_system_prompt: typing.Final = context.prompts.read("dossier_system.txt")
        style_result: typing.Final = context.style_prompt.apply_style_with_resolution(
            base_system_prompt,
            feature_cfg.style,
        )

        try:
            reply = await context.llm_executor.generate_text_with_pool(
                db=context.db,
                pool=pool,
                feature_settings=feature_cfg,
                system_prompt=style_result.system_prompt,
                user_prompt=context.prompts.render(
                    "dossier_user_template.txt",
                    username=dossier_target,
                    recent_block=recent_block,
                    memory_block=memory_block,
                ),
                style_resolution={
                    "requested_style": style_result.requested_style,
                    "applied_style": style_result.applied_style,
                    "style_resolution_status": style_result.style_resolution_status,
                    "style_resolution_reason": style_result.style_resolution_reason,
                },
            )
        except Exception:
            logger.exception("Dossier generation failed")
            reply = f"Не удалось собрать досье на @{normalized_target}"  # noqa: RUF001

        return FeatureResponse(
            reply_text=prepare_chat_text(reply, settings.twitch_message_limit),
            route=self.route_name,
        )


@typing.final
class WeeklyMoviesFeatureHandler(FeatureHandler):
    route_name = "weekly_movies"

    TRIGGERS: ClassVar[list[str]] = [
        "что смотрим",
        "что будем смотреть",
        "какие фильмы",
        "что на этой неделе",
        "что в списке",
        "что смотрим в воскресенье",
        "фильмы недели",
        "что по фильмам",
        "что у нас по фильмам",  # noqa: RUF001
        "что смотрим на этой неделе",
        "что на этой неделе смотрим",
        "какие фильмы на неделе",
    ]

    def matches(self, request: ChatRequest) -> bool:
        normalized: typing.Final = request.text.strip().lower()
        return any(trigger in normalized for trigger in self.TRIGGERS)

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:
        weekly_movies_data: typing.Final = context.weekly_movies.read_raw()

        if weekly_movies_data["found"] and weekly_movies_data["content"]:
            file_content = weekly_movies_data["content"]
        else:
            file_content = weekly_movies_data["message"] or "Список фильмов на эту неделю пока пуст."

        pool, feature_cfg = context.llm_registry.get_for_feature("weekly_movies")
        base_system_prompt: typing.Final = context.prompts.read("weekly_movies_system.txt")
        style_result: typing.Final = context.style_prompt.apply_style_with_resolution(
            base_system_prompt,
            feature_cfg.style,
        )

        try:
            reply = await context.llm_executor.generate_text_with_pool(
                db=context.db,
                pool=pool,
                feature_settings=feature_cfg,
                system_prompt=style_result.system_prompt,
                user_prompt=context.prompts.render(
                    "weekly_movies_user_template.txt",
                    user_text=request.text.strip(),
                    file_content=file_content,
                ),
                style_resolution={
                    "requested_style": style_result.requested_style,
                    "applied_style": style_result.applied_style,
                    "style_resolution_status": style_result.style_resolution_status,
                    "style_resolution_reason": style_result.style_resolution_reason,
                },
            )
        except Exception:
            logger.exception("Weekly movies reply failed")
            reply = "Не удалось прочитать список фильмов"  # noqa: RUF001

        return FeatureResponse(
            reply_text=prepare_chat_text(reply, settings.twitch_message_limit),
            route=self.route_name,
        )


@typing.final
class MentionChatFeatureHandler(FeatureHandler):
    route_name = "chat"

    def matches(self, request: ChatRequest) -> bool:
        return request.mentions_bot

    async def handle(self, context: FeatureContext, request: ChatRequest) -> FeatureResponse:
        normalized_username: typing.Final = request.username.strip().lstrip("@").lower()

        global_recent: typing.Final = context.chat_memory.recent_messages(
            context.db,
            stream_id=request.stream_id,
            limit=settings.chat_global_context_limit,
        )
        user_recent: typing.Final = context.chat_memory.recent_user_messages(
            context.db,
            stream_id=request.stream_id,
            username=normalized_username,
            limit=settings.chat_user_context_limit,
        )
        dialog_recent: typing.Final = context.chat_memory.recent_dialog_messages(
            context.db,
            stream_id=request.stream_id,
            username=normalized_username,
            limit=settings.chat_dialog_context_limit,
        )

        global_recent_block: typing.Final = (
            "\n".join(f"{m.username} [{m.role}]: {m.text}" for m in global_recent) or "Нет данных."
        )

        user_recent_block: typing.Final = (
            "\n".join(f"{m.username} [{m.role}]: {m.text}" for m in user_recent) or "Нет данных."
        )

        dialog_recent_block: typing.Final = (
            "\n".join(f"{m.username} [{m.role}]: {m.text}" for m in dialog_recent) or "Нет данных."
        )

        reply_context_block = "Нет"

        if request.reply_to_text:
            parent_user: typing.Final = request.reply_to_username or "unknown"
            reply_context_block = f"{parent_user}: {request.reply_to_text}"

        base_system_prompt: typing.Final = context.prompts.read("chat_system.txt")
        pool, feature_cfg = context.llm_registry.get_for_feature("chat")
        style_result: typing.Final = context.style_prompt.apply_style_with_resolution(
            base_system_prompt,
            feature_cfg.style,
        )

        user_prompt: typing.Final = context.prompts.render(
            "chat_user_template.txt",
            username=request.username,
            text=request.text.strip(),
            user_recent_block=user_recent_block,
            global_recent_block=global_recent_block,
            dialog_recent_block=dialog_recent_block,
            reply_context_block=reply_context_block,
        )

        try:
            reply = await context.llm_executor.generate_text_with_pool(
                db=context.db,
                pool=pool,
                feature_settings=feature_cfg,
                system_prompt=style_result.system_prompt,
                user_prompt=user_prompt,
                style_resolution={
                    "requested_style": style_result.requested_style,
                    "applied_style": style_result.applied_style,
                    "style_resolution_status": style_result.style_resolution_status,
                    "style_resolution_reason": style_result.style_resolution_reason,
                },
            )
        except Exception:
            logger.exception("Chat reply generation failed")
            reply = f"@{request.username}, не удалось получить ответ"

        return FeatureResponse(
            reply_text=prepare_chat_text(reply, settings.twitch_message_limit),
            route=self.route_name,
        )


@typing.final
class IgnoreFeatureHandler(FeatureHandler):
    route_name = "ignored"

    def matches(self, _request: ChatRequest) -> bool:
        return True

    async def handle(self, _context: FeatureContext, _request: ChatRequest) -> FeatureResponse:
        return FeatureResponse(reply_text="", route=self.route_name)
