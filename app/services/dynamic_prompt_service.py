from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.config import settings
from app.integrations.llm.base import LLMProvider
from app.prompt_store import PromptStore
from app.text_utils import prepare_chat_text

logger = logging.getLogger(__name__)


class DynamicPromptService:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        prompts: PromptStore,
    ) -> None:
        self.llm = llm
        self.prompts = prompts

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
        prompt_name: str,
        user: str,
        data: dict[str, Any],
    ) -> tuple[str, str]:
        """
        Returns:
            ("success", "<message>") on success
            ("fallback", "") on any recoverable failure
        """
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

        try:
            system_prompt = self.prompts.read(system_name)
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
            reply = await self.llm.generate_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
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