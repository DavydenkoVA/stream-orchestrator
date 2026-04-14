from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import admin_routes
from app.config import settings
from app.main import app


def _minimal_valid_payload() -> dict[str, str]:
    return {
        "providers[0][name]": "primary",
        "providers[0][provider]": "mock",
        "providers[0][models][0][name]": "model_a",
        "providers[0][models][0][api_key]": "admin-key",
        "providers[0][models][0][base_url]": "https://example.invalid",
        "providers[0][models][0][model]": "mock-a",
        "feature_settings[0][name]": "chat",
        "feature_settings[0][provider]": "primary",
        "feature_settings[0][temperature]": "0.7",
        "feature_settings[0][max_output_tokens]": "200",
        "feature_settings[0][style]": "default",
    }


def test_get_admin_llm_config_page_returns_404_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_admin_ui", False)
    client = TestClient(app)

    response = client.get("/admin/llm-config")

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"
    assert response.json()["message"] == "Not found"


def test_get_admin_llm_config_page_returns_200_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(admin_routes.settings, "enable_admin_ui", True)
    client = TestClient(app)

    response = client.get("/admin/llm-config")

    assert response.status_code == 200
    assert "LLM Config Admin" in response.text


def test_validate_route_returns_errors_for_invalid_payload(monkeypatch) -> None:
    monkeypatch.setattr(admin_routes.settings, "enable_admin_ui", True)
    client = TestClient(app)
    payload = _minimal_valid_payload()
    payload["providers[0][models][0][api_key]"] = ""

    response = client.post("/admin/llm-config/validate", data=payload)

    assert response.status_code == 200
    assert "Validation failed" in response.text
    assert "api_key is empty" in response.text


def test_apply_route_applies_new_config(monkeypatch) -> None:
    monkeypatch.setattr(admin_routes.settings, "enable_admin_ui", True)
    client = TestClient(app)
    payload = _minimal_valid_payload()
    payload["providers[0][models][0][api_key]"] = "admin-applied-key"

    response = client.post("/admin/llm-config/apply", data=payload)

    assert response.status_code == 200
    assert "Apply success" in response.text

    page = client.get("/admin/llm-config")
    assert "admin-applied-key" in page.text
