from __future__ import annotations

from app.services.style_registry import StyleRegistry
import logging


logger = logging.getLogger(__name__)

class StylePromptService:
    def __init__(self, style_registry: StyleRegistry) -> None:
        self.style_registry = style_registry

    def apply_style(self, base_system_prompt: str, style_name: str | None) -> str:
        style = self.style_registry.resolve(style_name)

        logger.info("LLM style selected: %s", style.key)

        if not style.instruction.strip():
            return base_system_prompt

        return (
            f"{base_system_prompt.strip()}\n\n"
            f"Дополнительная стилистическая инструкция:\n"
            f"{style.instruction.strip()}"
        )