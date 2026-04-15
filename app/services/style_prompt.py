from __future__ import annotations

from dataclasses import dataclass

from app.services.style_registry import StyleRegistry
import logging


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StyledPromptResult:
    system_prompt: str
    requested_style: str | None
    applied_style: str
    style_resolution_status: str
    style_resolution_reason: str


class StylePromptService:
    def __init__(self, style_registry: StyleRegistry) -> None:
        self.style_registry = style_registry

    def apply_style(self, base_system_prompt: str, style_name: str | None) -> str:
        return self.apply_style_with_resolution(base_system_prompt, style_name).system_prompt

    def apply_style_with_resolution(
        self,
        base_system_prompt: str,
        style_name: str | None,
    ) -> StyledPromptResult:
        resolution = self.style_registry.resolve_with_metadata(style_name)
        style = resolution.style

        logger.info("LLM style selected: %s", style.key)

        if not style.instruction.strip():
            return StyledPromptResult(
                system_prompt=base_system_prompt,
                requested_style=resolution.requested_style,
                applied_style=resolution.applied_style,
                style_resolution_status=resolution.status,
                style_resolution_reason=resolution.reason,
            )

        return StyledPromptResult(
            system_prompt=(
                f"{base_system_prompt.strip()}\n\n"
                f"Дополнительная стилистическая инструкция:\n"
                f"{style.instruction.strip()}"
            ),
            requested_style=resolution.requested_style,
            applied_style=resolution.applied_style,
            style_resolution_status=resolution.status,
            style_resolution_reason=resolution.reason,
        )
