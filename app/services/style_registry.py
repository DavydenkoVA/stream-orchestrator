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
        styles = self._load()

        if not style_name or not style_name.strip():
            return styles["default"]

        normalized = style_name.strip().lower()

        if normalized == "default":
            return styles["default"]

        if normalized == "random":
            candidates = [
                style
                for key, style in styles.items()
                if key not in {"default", "random"}
            ]
            if not candidates:
                return styles["default"]
            return random.choice(candidates)

        return styles.get(normalized, styles["default"])