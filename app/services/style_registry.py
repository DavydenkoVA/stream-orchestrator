from __future__ import annotations

import os
import random
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.config import settings

DEFAULT_STYLE_KEY = "default"
RANDOM_STYLE_KEY = "random"
STYLE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


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


@dataclass(slots=True)
class StyleSelectorOption:
    value: str
    label: str
    kind: str


class StyleRegistry:
    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = Path(config_path or settings.llm_styles_config_path)

    @staticmethod
    def default_style() -> StyleDefinition:
        return StyleDefinition(
            key=DEFAULT_STYLE_KEY,
            title="по умолчанию",
            instruction="",
        )

    def _read_raw(self) -> dict:
        if not self.config_path.exists():
            example_path = self.config_path.with_suffix(self.config_path.suffix + ".example")
            if example_path.exists():
                return yaml.safe_load(example_path.read_text(encoding="utf-8")) or {}
            return {}
        return yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def _load(self) -> dict[str, StyleDefinition]:
        raw = self._read_raw()
        styles_raw = raw.get("styles", {})

        styles: dict[str, StyleDefinition] = {}

        for key, cfg in styles_raw.items():
            normalized_key = str(key).strip().lower()
            if not normalized_key:
                continue

            style_cfg = cfg or {}
            styles[normalized_key] = StyleDefinition(
                key=normalized_key,
                title=str(style_cfg.get("title", normalized_key)).strip(),
                instruction=str(style_cfg.get("instruction", "")).strip(),
            )

        if DEFAULT_STYLE_KEY not in styles:
            styles[DEFAULT_STYLE_KEY] = self.default_style()

        return styles

    def list_configured_styles(self) -> list[StyleDefinition]:
        styles = self._load()
        keys = [DEFAULT_STYLE_KEY] + sorted(
            [key for key in styles.keys() if key != DEFAULT_STYLE_KEY]
        )
        return [styles[key] for key in keys]

    def selector_options(self) -> list[StyleSelectorOption]:
        options: list[StyleSelectorOption] = [
            StyleSelectorOption(value="", label="-- no style --", kind="empty"),
            StyleSelectorOption(value=RANDOM_STYLE_KEY, label=RANDOM_STYLE_KEY, kind="system"),
        ]
        options.extend(
            StyleSelectorOption(value=style.key, label=style.key, kind="configured")
            for style in self.list_configured_styles()
        )
        return options

    def validate_style_reference(self, style_name: str | None) -> str | None:
        if style_name is None:
            return None

        normalized = style_name.strip().lower()
        if not normalized:
            return None
        if normalized == RANDOM_STYLE_KEY:
            return None

        styles = self._load()
        if normalized not in styles:
            return f"unknown style reference: {normalized}"
        return None

    def validate_configured_styles(self, styles: list[StyleDefinition]) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        has_default = False

        for style in styles:
            key = style.key.strip().lower()
            if not key:
                errors.append("style name is empty")
                continue
            if not STYLE_NAME_PATTERN.fullmatch(key):
                errors.append(f"invalid style name: {key}")
                continue
            if key == RANDOM_STYLE_KEY:
                errors.append("style name 'random' is reserved")
            if key in seen:
                errors.append(f"duplicate style name: {key}")
                continue
            seen.add(key)

            if key == DEFAULT_STYLE_KEY:
                has_default = True

        if not has_default:
            errors.append("default style is required")

        return errors

    def apply_configured_styles(self, styles: list[StyleDefinition]) -> list[str]:
        errors = self.validate_configured_styles(styles)
        if errors:
            return errors

        styles_payload = {
            style.key: {
                "title": style.title,
                "instruction": style.instruction,
            }
            for style in styles
        }
        raw = {"styles": styles_payload}

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_payload = yaml.safe_dump(
            raw,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self.config_path.parent),
            delete=False,
            prefix=f"{self.config_path.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_file.write(yaml_payload)
            temp_path = Path(temp_file.name)

        try:
            os.replace(temp_path, self.config_path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

        return []

    def resolve(self, style_name: str | None) -> StyleDefinition:
        return self.resolve_with_metadata(style_name).style

    def resolve_with_metadata(self, style_name: str | None) -> StyleResolution:
        styles = self._load()

        if not style_name or not style_name.strip():
            style = styles[DEFAULT_STYLE_KEY]
            return StyleResolution(
                requested_style=None,
                applied_style=style.key,
                status="success",
                reason="missing_style_defaulted",
                style=style,
            )

        normalized = style_name.strip().lower()

        if normalized == DEFAULT_STYLE_KEY:
            style = styles[DEFAULT_STYLE_KEY]
            return StyleResolution(
                requested_style=normalized,
                applied_style=style.key,
                status="success",
                reason="default_used",
                style=style,
            )

        if normalized == RANDOM_STYLE_KEY:
            candidates = [
                style
                for key, style in styles.items()
                if key not in {DEFAULT_STYLE_KEY, RANDOM_STYLE_KEY}
            ]
            if not candidates:
                style = styles[DEFAULT_STYLE_KEY]
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

        fallback_style = styles[DEFAULT_STYLE_KEY]
        return StyleResolution(
            requested_style=normalized,
            applied_style=fallback_style.key,
            status="fallback",
            reason="style_not_found",
            style=fallback_style,
        )
