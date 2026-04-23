from pathlib import Path

import pytest

from app.prompt_store import PromptStore


def test_prompt_store_read_and_render(temp_prompts_dir: Path) -> None:
    store = PromptStore(base_dir=str(temp_prompts_dir))  # noqa: COP005

    assert store.read("chat_system.txt") == "Ты чат-ассистент."

    rendered = store.render("dynamic/test_template.txt", user="bob", loot="coins")  # noqa: COP011
    assert rendered == "hello bob, loot=coins"


def test_prompt_store_get_required_fields_simple_template(temp_prompts_dir: Path) -> None:
    store = PromptStore(base_dir=str(temp_prompts_dir))  # noqa: COP005

    assert store.get_required_fields("dynamic/test_template.txt") == {"user", "loot"}


def test_prompt_store_get_required_fields_escaped_braces(temp_prompts_dir: Path) -> None:
    template_path = temp_prompts_dir / "dynamic" / "escaped_template.txt"  # noqa: COP011
    template_path.write_text("text {{literal}} {user}", encoding="utf-8")

    store = PromptStore(base_dir=str(temp_prompts_dir))  # noqa: COP005

    assert store.get_required_fields("dynamic/escaped_template.txt") == {"user"}


def test_prompt_store_get_required_fields_invalid_syntax_raises_value_error(temp_prompts_dir: Path) -> None:
    broken_left = temp_prompts_dir / "dynamic" / "broken_left.txt"
    broken_right = temp_prompts_dir / "dynamic" / "broken_right.txt"
    broken_left.write_text("broken {", encoding="utf-8")
    broken_right.write_text("broken }", encoding="utf-8")

    store = PromptStore(base_dir=str(temp_prompts_dir))  # noqa: COP005

    with pytest.raises(ValueError, match="Invalid prompt template syntax"):
        store.get_required_fields("dynamic/broken_left.txt")

    with pytest.raises(ValueError, match="Invalid prompt template syntax"):
        store.get_required_fields("dynamic/broken_right.txt")


def test_prompt_store_get_required_fields_unsupported_placeholder_syntax(temp_prompts_dir: Path) -> None:
    template_path = temp_prompts_dir / "dynamic" / "unsupported_template.txt"  # noqa: COP011
    template_path.write_text("hello {user.name}", encoding="utf-8")

    store = PromptStore(base_dir=str(temp_prompts_dir))  # noqa: COP005

    with pytest.raises(ValueError, match="Unsupported placeholder syntax"):
        store.get_required_fields("dynamic/unsupported_template.txt")


def test_prompt_store_raises_for_missing_file(temp_prompts_dir: Path) -> None:
    store = PromptStore(base_dir=str(temp_prompts_dir))  # noqa: COP005

    with pytest.raises(FileNotFoundError):
        store.read("missing.txt")


def test_prompt_store_write_and_read_raw(temp_prompts_dir: Path) -> None:
    store = PromptStore(base_dir=str(temp_prompts_dir))  # noqa: COP005
    store.write("dynamic/new_template.txt", "  hello {user}\n")

    assert store.read_raw("dynamic/new_template.txt") == "  hello {user}\n"
    assert store.read("dynamic/new_template.txt") == "hello {user}"
