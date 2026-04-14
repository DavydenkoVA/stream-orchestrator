from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from sqlalchemy.orm import Session

from app.config import settings
from app.prompt_store import PromptStore
from app.services.llm_registry import LLMRegistry
from app.text_utils import prepare_chat_text
from app.services.style_prompt import StylePromptService
from app.services.llm_execution_service import LLMExecutionService


logger = logging.getLogger(__name__)


class DynamicPromptService:
    def __init__(
        self,
        *,
        llm_registry: LLMRegistry,
        llm_executor: LLMExecutionService,
        prompts: PromptStore,
        style_prompt: StylePromptService,
    ) -> None:
        self.llm_registry = llm_registry
        self.llm_executor = llm_executor
        self.prompts = prompts
        self.style_prompt = style_prompt

    def _validate_prompt_name(self, prompt_name: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_\-]+", prompt_name):
            raise ValueError("Invalid prompt name")
        return prompt_name

    def _resolve_prompt_names(self, prompt_name: str) -> tuple[str, str]:
        safe_name = self._validate_prompt_name(prompt_name)
        system_name = f"dynamic/{safe_name}_system.txt"
        template_name = f"dynamic/{safe_name}_template.txt"
        return system_name, template_name

    def _prompt_exists(self, relative_name: str) -> bool:
        prompt_path = Path(settings.prompts_dir) / relative_name
        return prompt_path.exists() and prompt_path.is_file()

    async def generate(
        self,
        *,
        db: Session,
        prompt_name: str,
        user: str,
        data: dict[str, Any],
        llm_provider_override: str | None = None,
        style_override: str | None = None,
        temperature_override: float | None = None,
        max_output_tokens_override: int | None = None,
    ) -> tuple[str, str]:
        try:
            system_name, template_name = self._resolve_prompt_names(prompt_name)
        except Exception:
            logger.warning("Dynamic prompt name validation failed: %s", prompt_name)
            return "fallback", ""

        if not self._prompt_exists(system_name) or not self._prompt_exists(template_name):
            logger.info(
                "Dynamic prompt files not found: prompt=%s system=%s template=%s",
                prompt_name,
                system_name,
                template_name,
            )
            return "fallback", ""

        if not isinstance(data, dict):
            return "fallback", ""

        pool, feature_cfg = self.llm_registry.get_for_feature_with_override(
            "dynamic_prompt",
            provider_override=llm_provider_override,
            style_override=style_override,
            temperature_override=temperature_override,
            max_output_tokens_override=max_output_tokens_override,
        )

        try:
            base_system_prompt = self.prompts.read(system_name)
            system_prompt = self.style_prompt.apply_style(
                base_system_prompt,
                feature_cfg.style,
            )
            user_prompt = self.prompts.render(
                template_name,
                user=user,
                **data,
            )
        except KeyError as e:
            logger.warning(
                "Dynamic prompt render failed due to missing field: prompt=%s missing=%s data_keys=%s",
                prompt_name,
                str(e),
                sorted(data.keys()),
            )
            return "fallback", ""
        except Exception:
            logger.exception("Dynamic prompt render failed: prompt=%s", prompt_name)
            return "fallback", ""

        try:
            reply = await self.llm_executor.generate_text_with_pool(
                db=db,
                pool=pool,
                feature_settings=feature_cfg,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception:
            logger.exception("Dynamic prompt LLM call failed: prompt=%s", prompt_name)
            return "fallback", ""

        if not reply or not reply.strip():
            logger.info("Dynamic prompt returned empty reply: prompt=%s", prompt_name)
            return "fallback", ""

        reply = prepare_chat_text(reply, settings.twitch_message_limit).strip()

        if not reply:
            logger.info("Dynamic prompt reply became empty after trim: prompt=%s", prompt_name)
            return "fallback", ""

        return "success", reply