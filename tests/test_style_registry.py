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


def test_style_resolution_random_default_invalid(monkeypatch) -> None:
    registry = StyleRegistry()

    monkeypatch.setattr(
        "app.services.style_registry.random.choice",
        lambda candidates: next(candidate for candidate in candidates if candidate.key == "fun"),
    )
    random_resolution = registry.resolve_with_metadata("random")
    assert random_resolution.requested_style == "random"
    assert random_resolution.applied_style == "fun"
    assert random_resolution.status == "success"
    assert random_resolution.reason == "random_resolved"

    default_resolution = registry.resolve_with_metadata("default")
    assert default_resolution.requested_style == "default"
    assert default_resolution.applied_style == "default"
    assert default_resolution.status == "success"
    assert default_resolution.reason == "default_used"

    invalid_resolution = registry.resolve_with_metadata("daark")
    assert invalid_resolution.requested_style == "daark"
    assert invalid_resolution.applied_style == "default"
    assert invalid_resolution.status == "fallback"
    assert invalid_resolution.reason == "style_not_found"
