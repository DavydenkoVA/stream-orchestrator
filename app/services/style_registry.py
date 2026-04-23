from __future__ import annotations
import dataclasses
import pathlib
import random
import re
import tempfile
import typing

import yaml

from app.config import settings


DEFAULT_STYLE_KEY: typing.Final = "default"
RANDOM_STYLE_KEY: typing.Final = "random"
STYLE_NAME_PATTERN: typing.Final = re.compile(r"^[a-zA-Z0-9_-]+$")


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class StyleDefinition:
    key: str  # noqa: COP004
    title: str  # noqa: COP004
    instruction: str


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class StyleResolution:
    requested_style: str | None
    applied_style: str
    status: str  # noqa: COP004
    reason: str  # noqa: COP004
    style: StyleDefinition  # noqa: COP004


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class StyleSelectorOption:
    value: str  # noqa: COP004
    label: str  # noqa: COP004
    kind: str  # noqa: COP004


@typing.final
class StyleRegistry:
    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = pathlib.Path(config_path or settings.llm_styles_config_path)

    @staticmethod
    def build_default_style() -> StyleDefinition:
        return StyleDefinition(
            key=DEFAULT_STYLE_KEY,
            title="по умолчанию",
            instruction="",
        )

    # Backward-compatible alias for existing call sites.
    @staticmethod
    def default_style() -> StyleDefinition:  # noqa: COP009
        return StyleRegistry.build_default_style()

    def read_raw_config(self) -> dict[str, object]:
        if not self.config_path.exists():
            example_path = self.config_path.with_suffix(self.config_path.suffix + ".example")
            if example_path.exists():
                return yaml.safe_load(example_path.read_text(encoding="utf-8")) or {}
            return {}
        return yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def load_configured_styles(self) -> dict[str, StyleDefinition]:
        style_items_raw = typing.cast("dict[str, dict[str, object]]", self.read_raw_config().get("styles", {}))

        style_by_key: dict[str, StyleDefinition] = {}
        for one_style_key, one_style_config in style_items_raw.items():
            normalized_style_key = str(one_style_key).strip().lower()
            if not normalized_style_key:
                continue

            style_by_key[normalized_style_key] = StyleDefinition(
                key=normalized_style_key,
                title=str(one_style_config.get("title", normalized_style_key)).strip(),
                instruction=str(one_style_config.get("instruction", "")).strip(),
            )

        if DEFAULT_STYLE_KEY not in style_by_key:
            style_by_key[DEFAULT_STYLE_KEY] = self.build_default_style()

        return style_by_key

    def list_configured_styles(self) -> list[StyleDefinition]:
        style_by_key = self.load_configured_styles()
        ordered_style_keys = [
            DEFAULT_STYLE_KEY,
            *sorted([one_style_key for one_style_key in style_by_key if one_style_key != DEFAULT_STYLE_KEY]),
        ]
        return [style_by_key[one_style_key] for one_style_key in ordered_style_keys]

    def build_selector_options(self) -> list[StyleSelectorOption]:
        selector_options: list[StyleSelectorOption] = [
            StyleSelectorOption(value="", label="-- no style --", kind="empty"),
            StyleSelectorOption(value=RANDOM_STYLE_KEY, label=RANDOM_STYLE_KEY, kind="system"),
        ]
        selector_options.extend(
            StyleSelectorOption(value=one_style.key, label=one_style.key, kind="configured")
            for one_style in self.list_configured_styles()
        )
        return selector_options

    def selector_options(self) -> list[StyleSelectorOption]:  # noqa: COP009
        return self.build_selector_options()

    def validate_style_reference(self, style_name: str | None) -> str | None:
        if style_name is None:
            return None

        normalized_style_name = style_name.strip().lower()
        if not normalized_style_name:
            return None
        if normalized_style_name == RANDOM_STYLE_KEY:
            return None

        if normalized_style_name not in self.load_configured_styles():
            return f"unknown style reference: {normalized_style_name}"
        return None

    def validate_configured_styles(self, configured_styles: list[StyleDefinition]) -> list[str]:
        validation_errors: list[str] = []
        seen_style_names: set[str] = set()
        has_default_style = False

        for one_style in configured_styles:
            normalized_style_key = one_style.key.strip().lower()
            if not normalized_style_key:
                validation_errors.append("style name is empty")
                continue
            if not STYLE_NAME_PATTERN.fullmatch(normalized_style_key):
                validation_errors.append(f"invalid style name: {normalized_style_key}")
                continue
            if normalized_style_key == RANDOM_STYLE_KEY:
                validation_errors.append("style name 'random' is reserved")
            if normalized_style_key in seen_style_names:
                validation_errors.append(f"duplicate style name: {normalized_style_key}")
                continue
            seen_style_names.add(normalized_style_key)

            if normalized_style_key == DEFAULT_STYLE_KEY:
                has_default_style = True

        if not has_default_style:
            validation_errors.append("default style is required")

        return validation_errors

    def apply_configured_styles(self, configured_styles: list[StyleDefinition]) -> list[str]:
        validation_errors = self.validate_configured_styles(configured_styles)
        if validation_errors:
            return validation_errors

        styles_payload = {
            one_style.key: {
                "title": one_style.title,
                "instruction": one_style.instruction,
            }
            for one_style in configured_styles
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_payload = yaml.safe_dump(
            {"styles": styles_payload},
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
            temporary_file_path = pathlib.Path(temp_file.name)

        try:
            temporary_file_path.replace(self.config_path)
        finally:
            if temporary_file_path.exists():
                temporary_file_path.unlink(missing_ok=True)

        return []

    def resolve_style(self, style_name: str | None) -> StyleDefinition:
        return self.resolve_with_metadata(style_name).style

    # Backward-compatible alias used by existing call sites.
    def resolve(self, style_name: str | None) -> StyleDefinition:  # noqa: COP007
        return self.resolve_style(style_name)

    def resolve_with_metadata(self, style_name: str | None) -> StyleResolution:
        configured_style_by_key = self.load_configured_styles()

        if not style_name or not style_name.strip():
            default_style = configured_style_by_key[DEFAULT_STYLE_KEY]
            return StyleResolution(
                requested_style=None,
                applied_style=default_style.key,
                status="success",
                reason="missing_style_defaulted",
                style=default_style,
            )

        normalized_style_name = style_name.strip().lower()

        if normalized_style_name == DEFAULT_STYLE_KEY:
            default_style = configured_style_by_key[DEFAULT_STYLE_KEY]
            return StyleResolution(
                requested_style=normalized_style_name,
                applied_style=default_style.key,
                status="success",
                reason="default_used",
                style=default_style,
            )

        if normalized_style_name == RANDOM_STYLE_KEY:
            random_candidates = [
                one_style
                for one_style_key, one_style in configured_style_by_key.items()
                if one_style_key not in {DEFAULT_STYLE_KEY, RANDOM_STYLE_KEY}
            ]
            if not random_candidates:
                default_style = configured_style_by_key[DEFAULT_STYLE_KEY]
                return StyleResolution(
                    requested_style=normalized_style_name,
                    applied_style=default_style.key,
                    status="fallback",
                    reason="random_no_candidates_defaulted",
                    style=default_style,
                )
            selected_style = random.choice(random_candidates)  # noqa: S311
            return StyleResolution(
                requested_style=normalized_style_name,
                applied_style=selected_style.key,
                status="success",
                reason="random_resolved",
                style=selected_style,
            )

        if normalized_style_name in configured_style_by_key:
            selected_style = configured_style_by_key[normalized_style_name]
            return StyleResolution(
                requested_style=normalized_style_name,
                applied_style=selected_style.key,
                status="success",
                reason="requested_applied",
                style=selected_style,
            )

        fallback_style = configured_style_by_key[DEFAULT_STYLE_KEY]
        return StyleResolution(
            requested_style=normalized_style_name,
            applied_style=fallback_style.key,
            status="fallback",
            reason="style_not_found",
            style=fallback_style,
        )
