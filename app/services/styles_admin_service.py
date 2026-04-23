from __future__ import annotations
import re
import typing
from dataclasses import dataclass  # noqa: COP002

from app.services.style_registry import DEFAULT_STYLE_KEY, StyleDefinition, StyleRegistry


@dataclass(slots=True)
class StylesValidationResult:  # noqa: COP012, COP014
    valid: bool  # noqa: COP004
    errors: list[str]  # noqa: COP004
    styles: list[StyleDefinition] | None = None  # noqa: COP004


class StylesAdminService:  # noqa: COP012
    STYLE_PATTERN = re.compile(r"^styles\[(\d+)\]\[(name|title|instruction|system)\]$")

    def __init__(self, style_registry: StyleRegistry) -> None:
        self.style_registry = style_registry

    def initial_styles(self) -> list[StyleDefinition]:  # noqa: COP009
        return self.style_registry.list_configured_styles()

    def parse_form_data(
        self,
        form: dict[str, str],  # noqa: COP006
    ) -> tuple[list[StyleDefinition], dict[int, str]]:
        styles_raw: typing.Final[dict[int, dict[str, str]]] = {}

        for key, value in form.items():
            match = self.STYLE_PATTERN.match(key)  # noqa: COP005
            if not match:
                continue
            idx = int(match.group(1))  # noqa: COP005
            field = match.group(2)  # noqa: COP005, COP011
            styles_raw.setdefault(idx, {})[field] = str(value).strip()

        styles: typing.Final[list[StyleDefinition]] = []  # noqa: COP005
        system_markers: typing.Final[dict[int, str]] = {}
        for idx in sorted(styles_raw.keys()):  # noqa: COP015
            row = styles_raw[idx]  # noqa: COP005
            system_marker = row.get("system", "").strip().lower()
            if system_marker:
                system_markers[idx] = system_marker
            name = row.get("name", "").strip().lower()  # noqa: COP005
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

    def validate_form_data(self, form: dict[str, str]) -> StylesValidationResult:  # noqa: COP006
        styles, system_markers = self.parse_form_data(form)
        errors: typing.Final = self.style_registry.validate_configured_styles(styles)  # noqa: COP005

        for idx, marker in system_markers.items():
            if marker != DEFAULT_STYLE_KEY:
                continue
            row_name = (form.get(f"styles[{idx}][name]") or "").strip().lower()  # noqa: COP011
            if row_name != DEFAULT_STYLE_KEY:
                errors.append("default style name cannot be changed")

        if DEFAULT_STYLE_KEY in [style.key for style in styles]:  # noqa: COP005, COP015
            default_item: typing.Final = next(style for style in styles if style.key == DEFAULT_STYLE_KEY)  # noqa: COP005, COP011, COP015
            if not default_item.title:
                errors.append("default style title is empty")

        if errors:
            return StylesValidationResult(valid=False, errors=errors)
        return StylesValidationResult(valid=True, errors=[], styles=styles)

    def apply_form_data(self, form: dict[str, str]) -> StylesValidationResult:  # noqa: COP006
        validation: typing.Final = self.validate_form_data(form)
        if not validation.valid or validation.styles is None:
            return validation

        errors: typing.Final = self.style_registry.apply_configured_styles(validation.styles)  # noqa: COP005
        if errors:
            return StylesValidationResult(valid=False, errors=errors)

        return validation
