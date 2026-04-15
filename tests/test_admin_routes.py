from __future__ import annotations

from fastapi.testclient import TestClient

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


def test_get_console_root_returns_200_with_sidebar_and_llm_screen() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Operator Console" in response.text
    assert "LLM Config" in response.text
    assert "Playground" in response.text
    assert "Traces" in response.text


def test_get_llm_config_page_returns_200() -> None:
    client = TestClient(app)

    response = client.get("/llm-config")

    assert response.status_code == 200
    assert "LLM Config" in response.text


def test_get_playground_returns_200() -> None:
    client = TestClient(app)

    response = client.get("/playground")

    assert response.status_code == 200
    assert "not implemented yet" in response.text


def test_get_traces_returns_200() -> None:
    client = TestClient(app)

    response = client.get("/traces")

    assert response.status_code == 200
    assert "not implemented yet" in response.text


def test_legacy_get_llm_config_redirects() -> None:
    client = TestClient(app)

    response = client.get("/admin/llm-config", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/llm-config"


def test_validate_route_returns_errors_for_invalid_payload() -> None:
    client = TestClient(app)
    payload = _minimal_valid_payload()
    payload["providers[0][models][0][api_key]"] = ""

    response = client.post("/llm-config/validate", data=payload)

    assert response.status_code == 200
    assert "Validation failed" in response.text
    assert "api_key is empty" in response.text


def test_apply_route_applies_new_config() -> None:
    client = TestClient(app)
    payload = _minimal_valid_payload()
    payload["providers[0][models][0][api_key]"] = "admin-applied-key"

    response = client.post("/llm-config/apply", data=payload)

    assert response.status_code == 200
    assert "Apply success" in response.text

    page = client.get("/llm-config")
    assert "admin-applied-key" in page.text


def test_legacy_validate_route_still_works() -> None:
    client = TestClient(app)
    payload = _minimal_valid_payload()

    response = client.post("/admin/llm-config/validate", data=payload)

    assert response.status_code == 200
    assert "Validation success" in response.text


def test_legacy_apply_route_still_works() -> None:
    client = TestClient(app)
    payload = _minimal_valid_payload()

    response = client.post("/admin/llm-config/apply", data=payload)

    assert response.status_code == 200
    assert "Apply success" in response.text


def test_apply_route_forbidden_outside_local_dev_test(monkeypatch) -> None:
    client = TestClient(app)
    payload = _minimal_valid_payload()
    monkeypatch.setattr("app.api.admin_routes.settings.app_env", "prod")

    response = client.post("/llm-config/apply", data=payload)

    assert response.status_code == 403


def test_legacy_apply_route_forbidden_outside_local_dev_test(monkeypatch) -> None:
    client = TestClient(app)
    payload = _minimal_valid_payload()
    monkeypatch.setattr("app.api.admin_routes.settings.app_env", "staging")

    response = client.post("/admin/llm-config/apply", data=payload)

    assert response.status_code == 403
