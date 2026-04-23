from __future__ import annotations
from typing import TYPE_CHECKING  # noqa: COP002

from app.services.style_registry import StyleRegistry
from app.services.styles_admin_service import StylesAdminService


if TYPE_CHECKING:
    from pathlib import Path


def _valid_styles_form() -> dict[str, str]:  # noqa: COP009
    return {
        "styles[0][name]": "default",
        "styles[0][system]": "default",
        "styles[0][title]": "Default",
        "styles[0][instruction]": "",
        "styles[1][name]": "fun",
        "styles[1][title]": "Fun",
        "styles[1][instruction]": "Joke",
    }


def test_validate_rejects_missing_default(temp_styles_config: Path) -> None:
    service = StylesAdminService(StyleRegistry(str(temp_styles_config)))  # noqa: COP005
    form = {  # noqa: COP005
        "styles[0][name]": "fun",
        "styles[0][system]": "default",
        "styles[0][title]": "Fun",
        "styles[0][instruction]": "Joke",
    }

    result = service.validate_form_data(form)  # noqa: COP005

    assert result.valid is False
    assert "default style is required" in result.errors


def test_validate_rejects_reserved_random_and_duplicates(temp_styles_config: Path) -> None:
    service = StylesAdminService(StyleRegistry(str(temp_styles_config)))  # noqa: COP005
    form = {  # noqa: COP005
        "styles[0][name]": "default",
        "styles[0][system]": "default",
        "styles[0][title]": "Default",
        "styles[0][instruction]": "",
        "styles[1][name]": "random",
        "styles[1][title]": "Random",
        "styles[1][instruction]": "",
        "styles[2][name]": "random",
        "styles[2][title]": "Duplicate",
        "styles[2][instruction]": "",
    }

    result = service.validate_form_data(form)  # noqa: COP005

    assert result.valid is False
    assert "style name 'random' is reserved" in result.errors
    assert "duplicate style name: random" in result.errors


def test_validate_rejects_invalid_style_name(temp_styles_config: Path) -> None:
    service = StylesAdminService(StyleRegistry(str(temp_styles_config)))  # noqa: COP005
    form = _valid_styles_form()  # noqa: COP005
    form["styles[1][name]"] = "bad.name"

    result = service.validate_form_data(form)  # noqa: COP005

    assert result.valid is False
    assert "invalid style name: bad.name" in result.errors


def test_validate_rejects_renamed_default_row(temp_styles_config: Path) -> None:
    service = StylesAdminService(StyleRegistry(str(temp_styles_config)))  # noqa: COP005
    form = _valid_styles_form()  # noqa: COP005
    form["styles[0][name]"] = "renamed_default"

    result = service.validate_form_data(form)  # noqa: COP005

    assert result.valid is False
    assert "default style name cannot be changed" in result.errors


def test_apply_creates_file_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "llm_styles.yml"  # noqa: COP005
    service = StylesAdminService(StyleRegistry(str(path)))  # noqa: COP005

    result = service.apply_form_data(_valid_styles_form())  # noqa: COP005

    assert result.valid is True
    assert path.exists()
    content = path.read_text(encoding="utf-8")  # noqa: COP005
    assert "styles:" in content
    assert "default:" in content


def test_selector_options_include_empty_random_and_configured(temp_styles_config: Path) -> None:
    registry = StyleRegistry(str(temp_styles_config))

    options = registry.selector_options()  # noqa: COP005

    assert options[0].value == ""
    assert options[1].value == "random"
    assert any(option.value == "default" for option in options)  # noqa: COP005, COP015
