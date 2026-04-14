from pathlib import Path

import pytest

from app.prompt_store import PromptStore


def test_prompt_store_read_and_render(temp_prompts_dir: Path) -> None:
    store = PromptStore(base_dir=str(temp_prompts_dir))

    assert store.read("chat_system.txt") == "Ты чат-ассистент."

    rendered = store.render("dynamic/test_template.txt", user="bob", loot="coins")
    assert "bob" in rendered
    assert "coins" in rendered


def test_prompt_store_raises_for_missing_file(temp_prompts_dir: Path) -> None:
    store = PromptStore(base_dir=str(temp_prompts_dir))

    with pytest.raises(FileNotFoundError):
        store.read("missing.txt")
