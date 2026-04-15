from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.config import settings


@dataclass(slots=True)
class StyleDefinition:
    key: str
    title: str
    instruction: str


@dataclass(slots=True)
class StyleResolution:
    requested_style: str | None
    applied_style: str
    status: str
    reason: str
    style: StyleDefinition


class StyleRegistry:
    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = Path(config_path or settings.llm_styles_config_path)

    def _load(self) -> dict[str, StyleDefinition]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"LLM styles config not found: {self.config_path}")

        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        styles_raw = raw.get("styles", {})

        if not styles_raw:
            return {
                "default": StyleDefinition(
                    key="default",
                    title="по умолчанию",
                    instruction="",
                )
            }

        styles: dict[str, StyleDefinition] = {}

        for key, cfg in styles_raw.items():
            styles[key] = StyleDefinition(
                key=key,
                title=str(cfg.get("title", key)).strip(),
                instruction=str(cfg.get("instruction", "")).strip(),
            )

        if "default" not in styles:
            styles["default"] = StyleDefinition(
                key="default",
                title="по умолчанию",
                instruction="",
            )

        return styles

    def resolve(self, style_name: str | None) -> StyleDefinition:
        return self.resolve_with_metadata(style_name).style

    def resolve_with_metadata(self, style_name: str | None) -> StyleResolution:
        styles = self._load()

        if not style_name or not style_name.strip():
            style = styles["default"]
            return StyleResolution(
                requested_style=None,
                applied_style=style.key,
                status="success",
                reason="missing_style_defaulted",
                style=style,
            )

        normalized = style_name.strip().lower()

        if normalized == "default":
            style = styles["default"]
            return StyleResolution(
                requested_style=normalized,
                applied_style=style.key,
                status="success",
                reason="default_used",
                style=style,
            )

        if normalized == "random":
            candidates = [
                style
                for key, style in styles.items()
                if key not in {"default", "random"}
            ]
            if not candidates:
                style = styles["default"]
                return StyleResolution(
                    requested_style=normalized,
                    applied_style=style.key,
                    status="fallback",
                    reason="random_no_candidates_defaulted",
                    style=style,
                )
            style = random.choice(candidates)
            return StyleResolution(
                requested_style=normalized,
                applied_style=style.key,
                status="success",
                reason="random_resolved",
                style=style,
            )

        if normalized in styles:
            style = styles[normalized]
            return StyleResolution(
                requested_style=normalized,
                applied_style=style.key,
                status="success",
                reason="requested_applied",
                style=style,
            )

        fallback_style = styles["default"]
        return StyleResolution(
            requested_style=normalized,
            applied_style=fallback_style.key,
            status="fallback",
            reason="style_not_found",
            style=fallback_style,
        )
