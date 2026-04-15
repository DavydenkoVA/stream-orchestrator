from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.style_registry import DEFAULT_STYLE_KEY, StyleDefinition, StyleRegistry


@dataclass(slots=True)
class StylesValidationResult:
    valid: bool
    errors: list[str]
    styles: list[StyleDefinition] | None = None


class StylesAdminService:
    STYLE_PATTERN = re.compile(r"^styles\[(\d+)\]\[(name|title|instruction|system)\]$")

    def __init__(self, style_registry: StyleRegistry) -> None:
        self.style_registry = style_registry

    def initial_styles(self) -> list[StyleDefinition]:
        return self.style_registry.list_configured_styles()

    def parse_form_data(
        self,
        form: dict[str, str],
    ) -> tuple[list[StyleDefinition], dict[int, str]]:
        styles_raw: dict[int, dict[str, str]] = {}

        for key, value in form.items():
            match = self.STYLE_PATTERN.match(key)
            if not match:
                continue
            idx = int(match.group(1))
            field = match.group(2)
            styles_raw.setdefault(idx, {})[field] = str(value).strip()

        styles: list[StyleDefinition] = []
        system_markers: dict[int, str] = {}
        for idx in sorted(styles_raw.keys()):
            row = styles_raw[idx]
            system_marker = row.get("system", "").strip().lower()
            if system_marker:
                system_markers[idx] = system_marker
            name = row.get("name", "").strip().lower()
            if not name:
                continue
            styles.append(
                StyleDefinition(
                    key=name,
                    title=row.get("title", "").strip(),
                    instruction=row.get("instruction", "").strip(),
                )
            )
        return styles, system_markers

    def validate_form_data(self, form: dict[str, str]) -> StylesValidationResult:
        styles, system_markers = self.parse_form_data(form)
        errors = self.style_registry.validate_configured_styles(styles)

        for idx, marker in system_markers.items():
            if marker != DEFAULT_STYLE_KEY:
                continue
            row_name = (form.get(f"styles[{idx}][name]") or "").strip().lower()
            if row_name != DEFAULT_STYLE_KEY:
                errors.append("default style name cannot be changed")

        if DEFAULT_STYLE_KEY in [style.key for style in styles]:
            default_item = next(style for style in styles if style.key == DEFAULT_STYLE_KEY)
            if not default_item.title:
                errors.append("default style title is empty")

        if errors:
            return StylesValidationResult(valid=False, errors=errors)
        return StylesValidationResult(valid=True, errors=[], styles=styles)

    def apply_form_data(self, form: dict[str, str]) -> StylesValidationResult:
        validation = self.validate_form_data(form)
        if not validation.valid or validation.styles is None:
            return validation

        errors = self.style_registry.apply_configured_styles(validation.styles)
        if errors:
            return StylesValidationResult(valid=False, errors=errors)

        return validation
