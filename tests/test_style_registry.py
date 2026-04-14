from app.services.style_prompt import StylePromptService
from app.services.style_registry import StyleRegistry


def test_style_registry_resolves_default_and_named_styles() -> None:
    registry = StyleRegistry()

    default_style = registry.resolve(None)
    fun_style = registry.resolve("fun")
    unknown = registry.resolve("unknown")

    assert default_style.key == "default"
    assert fun_style.key == "fun"
    assert unknown.key == "default"


def test_style_registry_random_selects_new_style_each_call(monkeypatch) -> None:
    registry = StyleRegistry()

    returned = iter(["fun", "strict"])

    def fake_choice(candidates):
        selected_key = next(returned)
        for candidate in candidates:
            if candidate.key == selected_key:
                return candidate
        raise AssertionError("candidate not found")

    monkeypatch.setattr("app.services.style_registry.random.choice", fake_choice)

    first = registry.resolve("random")
    second = registry.resolve("random")

    assert first.key == "fun"
    assert second.key == "strict"


def test_style_prompt_service_applies_instruction() -> None:
    service = StylePromptService(StyleRegistry())

    styled = service.apply_style("system-base", "strict")

    assert "system-base" in styled
    assert "Дополнительная стилистическая инструкция" in styled
