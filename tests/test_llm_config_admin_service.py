from __future__ import annotations

from pathlib import Path

from app.services.llm_config_admin_service import LLMConfigAdminService
from app.services.llm_registry import LLMRegistry
from app.services.llm_config_source import SUPPORTED_FEATURE_NAMES


def _valid_form_data() -> dict[str, str]:
    payload = {
        "providers[0][name]": "primary",
        "providers[0][provider]": "mock",
        "providers[0][models][0][name]": "model_a",
        "providers[0][models][0][api_key]": "new-key-a",
        "providers[0][models][0][base_url]": "https://example.invalid",
        "providers[0][models][0][model]": "mock-a",
    }

    for idx, feature_name in enumerate(SUPPORTED_FEATURE_NAMES):
        payload[f"feature_settings[{idx}][name]"] = feature_name
        payload[f"feature_settings[{idx}][provider]"] = "primary"
        payload[f"feature_settings[{idx}][temperature]"] = "0.8"
        payload[f"feature_settings[{idx}][max_output_tokens]"] = "300"
        payload[f"feature_settings[{idx}][style]"] = "default"

    return payload


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


def test_missing_config_file_read_and_apply_creates_path(tmp_path: Path) -> None:
    config_path = tmp_path / 'nested' / 'llm_profiles.yml'
    registry = LLMRegistry(config_path=str(config_path))
    admin_service = LLMConfigAdminService(registry)

    raw = admin_service.read_raw_config()
    assert raw == {}

    result = admin_service.apply_form_data(_valid_form_data())

    assert result.valid is True
    assert config_path.exists()
    payload = config_path.read_text(encoding='utf-8')
    assert 'providers:' in payload
    assert 'feature_settings:' in payload

    reread = admin_service.read_raw_config()
    assert reread['providers']['primary']['provider'] == 'mock'
    assert set(reread['feature_settings'].keys()) == set(SUPPORTED_FEATURE_NAMES)


def test_validate_rejects_unknown_provider_type() -> None:
    registry = LLMRegistry()
    admin_service = LLMConfigAdminService(registry)
    form_data = _valid_form_data()
    form_data['providers[0][provider]'] = 'unknown'

    result = admin_service.validate_form_data(form_data)

    assert result.valid is False
    assert any('unsupported provider type' in error for error in result.errors)


def test_validate_rejects_out_of_range_temperature() -> None:
    registry = LLMRegistry()
    admin_service = LLMConfigAdminService(registry)
    form_data = _valid_form_data()
    form_data['feature_settings[0][temperature]'] = '1.5'

    result = admin_service.validate_form_data(form_data)

    assert result.valid is False
    assert 'invalid temperature' in result.errors


def test_validate_rejects_unknown_style_reference() -> None:
    registry = LLMRegistry()
    admin_service = LLMConfigAdminService(registry)
    form_data = _valid_form_data()
    form_data['feature_settings[0][style]'] = 'missing_style'

    result = admin_service.validate_form_data(form_data)

    assert result.valid is False
    assert "feature 'chat': unknown style reference: missing_style" in result.errors
