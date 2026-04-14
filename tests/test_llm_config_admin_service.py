from __future__ import annotations

from pathlib import Path

from app.services.llm_config_admin_service import LLMConfigAdminService
from app.services.llm_registry import LLMRegistry


def _valid_form_data() -> dict[str, str]:
    return {
        "providers[0][name]": "primary",
        "providers[0][provider]": "mock",
        "providers[0][models][0][name]": "model_a",
        "providers[0][models][0][api_key]": "new-key-a",
        "providers[0][models][0][base_url]": "https://example.invalid",
        "providers[0][models][0][model]": "mock-a",
        "feature_settings[0][name]": "chat",
        "feature_settings[0][provider]": "primary",
        "feature_settings[0][temperature]": "0.8",
        "feature_settings[0][max_output_tokens]": "300",
        "feature_settings[0][style]": "default",
    }


def test_form_validation_returns_human_errors() -> None:
    registry = LLMRegistry()
    admin_service = LLMConfigAdminService(registry)
    form_data = _valid_form_data()
    form_data["providers[0][models][0][api_key]"] = ""

    result = admin_service.validate_form_data(form_data)

    assert result.valid is False
    assert "api_key is empty" in result.errors


def test_apply_does_not_write_file_when_invalid(temp_llm_profiles: Path) -> None:
    registry = LLMRegistry()
    admin_service = LLMConfigAdminService(registry)

    original_content = temp_llm_profiles.read_text(encoding="utf-8")
    form_data = _valid_form_data()
    form_data["feature_settings[0][provider]"] = "missing"

    result = admin_service.apply_form_data(form_data)

    assert result.valid is False
    assert temp_llm_profiles.read_text(encoding="utf-8") == original_content


def test_apply_writes_file_when_valid(temp_llm_profiles: Path) -> None:
    registry = LLMRegistry()
    admin_service = LLMConfigAdminService(registry)

    form_data = _valid_form_data()
    result = admin_service.apply_form_data(form_data)

    assert result.valid is True
    content = temp_llm_profiles.read_text(encoding="utf-8")
    assert "new-key-a" in content
    assert "max_output_tokens: 300" in content


def test_reload_does_not_break_active_snapshot_on_invalid_candidate() -> None:
    registry = LLMRegistry()
    admin_service = LLMConfigAdminService(registry)

    original_pool = registry.get_provider_pool("primary")
    form_data = _valid_form_data()
    form_data["feature_settings[0][provider]"] = "unknown_provider"

    result = admin_service.apply_form_data(form_data)

    assert result.valid is False
    pool_after = registry.get_provider_pool("primary")
    assert pool_after.provider == original_pool.provider
    assert len(pool_after.models) == len(original_pool.models)
