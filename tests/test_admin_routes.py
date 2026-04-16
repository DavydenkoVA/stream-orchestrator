from __future__ import annotations
import json
import re
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.chat import ChatMessage
from app.models.trace_event import TraceEvent
from app.models.trace_run import TraceRun
from app.observability.trace_status import TRACE_RUN_ALLOWED_STATUSES, TRACE_STATUS_FILTER_ALL
from app.services.llm_config_source import SUPPORTED_FEATURE_NAMES


EXPECTED_RECENT_ITEMS = 2


if TYPE_CHECKING:
    from collections.abc import Generator

    import pytest
    from sqlalchemy.orm import Session


def _minimal_valid_payload() -> dict[str, str]:
    request_payload = {
        "providers[0][name]": "primary",
        "providers[0][provider]": "mock",
        "providers[0][models][0][name]": "model_a",
        "providers[0][models][0][api_key]": "admin-key",
        "providers[0][models][0][base_url]": "https://example.invalid",
        "providers[0][models][0][model]": "mock-a",
    }

    for idx, feature_name in enumerate(SUPPORTED_FEATURE_NAMES):
        request_payload[f"feature_settings[{idx}][name]"] = feature_name
        request_payload[f"feature_settings[{idx}][provider]"] = "primary"
        request_payload[f"feature_settings[{idx}][temperature]"] = "0.7"
        request_payload[f"feature_settings[{idx}][max_output_tokens]"] = "200"
        request_payload[f"feature_settings[{idx}][style]"] = "default"

    return request_payload


def test_get_console_root_returns_200_with_sidebar_and_llm_screen() -> None:
    test_client = TestClient(app)

    response = test_client.get("/")

    assert response.status_code == HTTPStatus.OK
    assert "Operator Console" in response.text
    assert "LLM Config" in response.text
    assert "Styles" in response.text
    assert "Playground" in response.text
    assert "Traces" in response.text


def test_get_llm_config_page_returns_200() -> None:
    test_client = TestClient(app)

    response = test_client.get("/llm-config")

    assert response.status_code == HTTPStatus.OK
    assert "LLM Config" in response.text


def test_llm_config_renders_operator_safe_controls() -> None:
    test_client = TestClient(app)

    response = test_client.get("/llm-config")

    assert response.status_code == HTTPStatus.OK
    assert "Provider type" in response.text
    assert 'class="provider-type-select"' in response.text
    assert "+ Add feature" not in response.text
    assert 'class="remove-feature"' not in response.text
    assert "feature-provider-select" in response.text
    assert "feature-style-select" in response.text
    assert "Styles config (read-only preview)" not in response.text
    assert 'type="range"' in response.text


def test_llm_config_provider_options_use_top_level_provider_names_only() -> None:
    test_client = TestClient(app)

    response = test_client.get("/llm-config")

    assert response.status_code == HTTPStatus.OK
    assert 'providerOptions: ["primary"]' in response.text
    assert 'providerOptions: ["primary", "model_a"]' not in response.text
    assert 'providerOptions: ["primary", "model_b"]' not in response.text


def test_llm_config_js_collects_only_top_level_provider_name_inputs() -> None:
    test_client = TestClient(app)

    response = test_client.get("/static/admin/llm_config.js")

    assert response.status_code == HTTPStatus.OK
    assert "document.querySelectorAll('.provider-item .provider-name-input')" in response.text
    assert "document.querySelectorAll('.provider-item input[name$=\"[name]\"]')" not in response.text


def test_get_styles_page_returns_200_and_shows_default() -> None:
    test_client = TestClient(app)
    response = test_client.get("/styles")

    assert response.status_code == HTTPStatus.OK
    assert "Manage configured styles" in response.text
    assert 'id="add-style-btn"' in response.text
    assert '<input value="default" disabled>' in response.text
    assert 'name="styles[0][name]" value="default"' in response.text
    assert 'name="styles[0][system]" value="default"' in response.text


def test_get_styles_page_keeps_non_default_name_editable() -> None:
    test_client = TestClient(app)
    response = test_client.get("/styles")

    assert response.status_code == HTTPStatus.OK
    assert 'name="styles[1][name]" value="fun"' in response.text
    assert 'name="styles[1][name]" value="fun" disabled' not in response.text


def test_styles_js_does_not_reinitialize_default_name_field() -> None:
    test_client = TestClient(app)
    response = test_client.get("/static/admin/styles.js")

    assert response.status_code == HTTPStatus.OK
    assert "querySelectorAll('.style-item').forEach(bindRemoveButton);" in response.text
    assert "readonly" not in response.text
    assert "removeAttribute" not in response.text


def test_get_playground_returns_200() -> None:
    test_client = TestClient(app)

    response = test_client.get("/playground")

    assert response.status_code == HTTPStatus.OK
    assert "Chat Reply" in response.text
    assert "Dynamic Prompt" in response.text
    assert "Dossier" in response.text
    assert "Delete test data" in response.text


def test_get_playground_with_dynamic_mode_returns_200() -> None:
    test_client = TestClient(app)

    response = test_client.get("/playground", params={"mode": "dynamic"})

    assert response.status_code == HTTPStatus.OK
    assert 'data-initial-mode="dynamic"' in response.text
    assert "Payload template" in response.text
    assert 'id="dynamic-copy-template-btn"' in response.text
    assert 'id="dynamic-new-prompt-btn"' in response.text


def test_playground_dynamic_override_renders_select_and_slider() -> None:
    test_client = TestClient(app)

    response = test_client.get("/playground", params={"mode": "dynamic"})

    assert response.status_code == HTTPStatus.OK
    assert 'id="dynamic-provider-select"' in response.text
    assert '<select name="provider" id="dynamic-provider-select">' in response.text
    assert 'id="dynamic-style-select"' in response.text
    assert '<option value="random">random</option>' in response.text
    assert 'name="temperature" type="range"' in response.text
    assert 'id="dynamic-temperature-value"' in response.text


def test_playground_dynamic_provider_options_exclude_model_names() -> None:
    test_client = TestClient(app)

    response = test_client.get("/playground", params={"mode": "dynamic"})

    assert response.status_code == HTTPStatus.OK
    assert '<option value="primary">primary</option>' in response.text
    assert '<option value="model_a">model_a</option>' not in response.text
    assert '<option value="model_b">model_b</option>' not in response.text


def test_get_dynamic_prompt_names_endpoint_filters_incomplete_pairs(
    temp_prompts_dir: Path,
) -> None:
    test_client = TestClient(app)

    dynamic_dir = temp_prompts_dir / "dynamic"
    (dynamic_dir / "weekly_summary_system.txt").write_text("system", encoding="utf-8")
    (dynamic_dir / "weekly_summary_template.txt").write_text("hello {foo}", encoding="utf-8")
    (dynamic_dir / "incomplete_system.txt").write_text("system", encoding="utf-8")

    response = test_client.get("/playground/api/dynamic-prompts")

    assert response.status_code == HTTPStatus.OK
    prompt_names = [one_item["name"] for one_item in response.json()["items"]]
    assert prompt_names == ["test", "weekly_summary"]


def test_get_dynamic_prompt_metadata_returns_full_payload() -> None:
    test_client = TestClient(app)

    response = test_client.get("/playground/api/dynamic-prompts/test")

    assert response.status_code == HTTPStatus.OK
    request_payload = response.json()
    assert request_payload["name"] == "test"
    assert request_payload["required_fields"] == ["loot", "user"]
    assert request_payload["required_data_fields"] == ["loot"]
    assert request_payload["data_skeleton"] == {"loot": ""}
    assert request_payload["system_prompt"] == "dynamic system"
    assert request_payload["template_prompt"] == "hello {user}, loot={loot}"


def test_create_dynamic_prompt_creates_both_files_and_lists() -> None:
    test_client = TestClient(app)

    response = test_client.post("/playground/api/dynamic-prompts/create", json={"name": "new_prompt"})
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"name": "new_prompt", "created": True}

    list_response = test_client.get("/playground/api/dynamic-prompts")
    prompt_names = [one_item["name"] for one_item in list_response.json()["items"]]
    assert "new_prompt" in prompt_names

    prompts_payload = test_client.get("/playground/api/prompts/dynamic", params={"name": "new_prompt"}).json()
    assert prompts_payload["items"][0]["content"] == ""
    assert prompts_payload["items"][1]["content"] == ""


def test_create_dynamic_prompt_rejects_invalid_or_duplicate_name() -> None:
    test_client = TestClient(app)

    invalid = test_client.post("/playground/api/dynamic-prompts/create", json={"name": "../bad"})
    assert invalid.status_code == HTTPStatus.BAD_REQUEST

    duplicate = test_client.post("/playground/api/dynamic-prompts/create", json={"name": "test"})
    assert duplicate.status_code == HTTPStatus.BAD_REQUEST


def test_playground_prompt_save_updates_runtime_read() -> None:
    test_client = TestClient(app)

    save_response = test_client.post(
        "/playground/api/prompts/save",
        json={"scope": "chat", "part": "system_prompt", "content": "UPDATED CHAT SYSTEM"},
    )
    assert save_response.status_code == HTTPStatus.OK

    debug_prompt = test_client.get("/debug/prompts/chat_system.txt")
    assert debug_prompt.status_code == HTTPStatus.OK
    assert debug_prompt.json()["content"] == "UPDATED CHAT SYSTEM"


def test_playground_chat_and_dossier_prompt_load_routes() -> None:
    test_client = TestClient(app)

    chat = test_client.get("/playground/api/prompts/chat")
    assert chat.status_code == HTTPStatus.OK
    chat_parts = {one_item["part"] for one_item in chat.json()["items"]}
    assert chat_parts == {"system_prompt", "user_template"}

    dossier = test_client.get("/playground/api/prompts/dossier")
    assert dossier.status_code == HTTPStatus.OK
    dossier_parts = {one_item["part"] for one_item in dossier.json()["items"]}
    assert dossier_parts == {"system_prompt", "user_template"}


def test_playground_dossier_run_uses_real_route_and_trace_header(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    response = test_client.post(
        "/playground/api/dossier/run",
        json={"stream_id": "stream_d", "username": "viewer", "dossier_target": "target_user"},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["route"] == "dossier"
    trace_id = response.headers.get("X-Trace-Id")
    assert trace_id
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
    app.dependency_overrides.clear()


def test_playground_layout_and_button_classes_present() -> None:
    test_client = TestClient(app)
    response = test_client.get("/playground")
    assert response.status_code == HTTPStatus.OK
    assert 'class="btn-run"' in response.text
    assert 'class="btn-delete"' in response.text
    assert 'class="btn-reset"' in response.text
    assert 'id="chat-system-editor"' in response.text
    assert 'id="dossier-system-editor"' in response.text
    assert 'class="playground-two-col"' in response.text


def test_chat_reply_layout_and_context_tabs_and_reply_fields() -> None:
    test_client = TestClient(app)
    response = test_client.get("/playground", params={"mode": "chat"})
    assert response.status_code == HTTPStatus.OK
    assert 'data-context-tab="system_prompt"' not in response.text
    assert 'data-context-tab="user_prompt"' not in response.text
    assert 'name="reply_to_message_id"' in response.text
    assert 'name="reply_to_username"' in response.text
    assert 'name="reply_to_text"' in response.text
    assert 'class="playground-col-right"' in response.text
    assert "Prompts" in response.text
    assert "Reply Result" in response.text


def test_dynamic_layout_right_column_and_skeleton_logic_present_in_js() -> None:
    test_client = TestClient(app)
    html = test_client.get("/playground", params={"mode": "dynamic"})
    assert html.status_code == HTTPStatus.OK
    assert 'class="playground-col-right"' in html.text
    assert "Run Result" in html.text
    assert "Prompts" in html.text

    js = test_client.get("/static/admin/playground.js")
    assert js.status_code == HTTPStatus.OK
    assert "function buildDynamicDataSkeleton" in js.text
    assert "field !== 'user'" in js.text
    assert "dynamicData.value = formatPayload(buildDynamicDataSkeleton(dynamicPromptMeta));" in js.text


def test_playground_css_uses_vertical_resize() -> None:
    test_client = TestClient(app)
    response = test_client.get("/static/admin/console.css")
    assert response.status_code == HTTPStatus.OK
    assert "resize: vertical;" in response.text


def test_playground_copy_feedback_is_transient() -> None:
    test_client = TestClient(app)
    response = test_client.get("/static/admin/playground.js")
    assert response.status_code == HTTPStatus.OK
    assert "setTimeout" in response.text
    assert "dynamicCopyStatus.hidden = true" in response.text


def test_trace_link_source_uses_response_header() -> None:
    test_client = TestClient(app)
    response = test_client.get("/static/admin/playground.js")
    assert response.status_code == HTTPStatus.OK
    assert "response.headers.get('X-Trace-Id')" in response.text


def test_reset_stream_deletes_messages_and_is_idempotent(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)

    db_session.add_all(
        [
            ChatMessage(stream_id="stream_a", username="u1", role="viewer", text="hello", mentions_bot=False),
            ChatMessage(stream_id="stream_a", username="u1", role="bot", text="reply", mentions_bot=False),
            ChatMessage(stream_id="stream_b", username="u2", role="viewer", text="other", mentions_bot=False),
        ]
    )
    db_session.commit()

    context_before = test_client.get(
        "/debug/context",
        params={"stream_id": "stream_a", "username": "u1", "text": "ping"},
    )
    assert context_before.status_code == HTTPStatus.OK
    assert len(context_before.json()["global_recent"]) == EXPECTED_RECENT_ITEMS

    first = test_client.post("/playground/api/chat/reset-stream", json={"stream_id": "stream_a"})
    assert first.status_code == HTTPStatus.OK
    assert first.json()["deleted"] is True
    assert first.json()["deleted_count"] == EXPECTED_RECENT_ITEMS

    context_after = test_client.get(
        "/debug/context",
        params={"stream_id": "stream_a", "username": "u1", "text": "ping"},
    )
    assert context_after.status_code == HTTPStatus.OK
    assert context_after.json()["global_recent"] == []

    second = test_client.post("/playground/api/chat/reset-stream", json={"stream_id": "stream_a"})
    assert second.status_code == HTTPStatus.OK
    assert second.json()["deleted"] is True
    assert second.json()["deleted_count"] == 0

    untouched_context = test_client.get(
        "/debug/context",
        params={"stream_id": "stream_b", "username": "u2", "text": "ping"},
    )
    assert untouched_context.status_code == HTTPStatus.OK
    assert len(untouched_context.json()["global_recent"]) == 1

    app.dependency_overrides.clear()


def test_reset_stream_rejects_empty_stream_id(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)

    response = test_client.post("/playground/api/chat/reset-stream", json={"stream_id": ""})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    app.dependency_overrides.clear()


def test_get_dynamic_prompt_metadata_invalid_name_returns_400() -> None:
    test_client = TestClient(app)

    response = test_client.get("/playground/api/dynamic-prompts/bad.name")

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_get_dynamic_prompt_metadata_missing_prompt_returns_404() -> None:
    test_client = TestClient(app)

    response = test_client.get("/playground/api/dynamic-prompts/missing")

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_get_traces_returns_200_with_empty_state() -> None:
    test_client = TestClient(app)

    response = test_client.get("/traces")

    assert response.status_code == HTTPStatus.OK
    assert "Select a trace run to inspect details" in response.text
    assert 'id="traces-status"' in response.text
    assert '<input id="traces-status"' not in response.text
    assert f'<option value="{TRACE_STATUS_FILTER_ALL}">{TRACE_STATUS_FILTER_ALL}</option>' in response.text
    for status in TRACE_RUN_ALLOWED_STATUSES:
        assert f'<option value="{status}">{status}</option>' in response.text


def test_get_traces_with_run_id_returns_200(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)

    run = TraceRun(
        trace_id="trace-page-run",
        request_id="req-page-run",
        route="/events/chat_reply",
        stream_id="stream-page",
        status="success",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()

    response = test_client.get("/traces", params={"run_id": "trace-page-run"})

    assert response.status_code == HTTPStatus.OK
    assert 'data-selected-run-id="trace-page-run"' in response.text

    app.dependency_overrides.clear()


def test_legacy_get_llm_config_redirects() -> None:
    test_client = TestClient(app)

    response = test_client.get("/admin/llm-config", follow_redirects=False)

    assert response.status_code == HTTPStatus.TEMPORARY_REDIRECT
    assert response.headers["location"] == "/llm-config"


def test_validate_route_returns_errors_for_invalid_payload() -> None:
    test_client = TestClient(app)
    request_payload = _minimal_valid_payload()
    request_payload["providers[0][models][0][api_key]"] = ""

    response = test_client.post("/llm-config/validate", data=request_payload)

    assert response.status_code == HTTPStatus.OK
    assert "Validation failed" in response.text
    assert "api_key is empty" in response.text


def test_apply_route_applies_new_config() -> None:
    test_client = TestClient(app)
    request_payload = _minimal_valid_payload()
    request_payload["providers[0][models][0][api_key]"] = "admin-applied-key"

    response = test_client.post("/llm-config/apply", data=request_payload)

    assert response.status_code == HTTPStatus.OK
    assert "Apply success" in response.text

    page = test_client.get("/llm-config")
    assert "admin-applied-key" in page.text


def test_styles_validate_and_apply_routes_work() -> None:
    test_client = TestClient(app)
    request_payload = {
        "styles[0][name]": "default",
        "styles[0][system]": "default",
        "styles[0][title]": "Default title updated",
        "styles[0][instruction]": "Default instruction updated",
        "styles[1][name]": "cinematic",
        "styles[1][title]": "Cinematic",
        "styles[1][instruction]": "Use cinematic language.",
    }

    validate_response = test_client.post("/styles/validate", data=request_payload)
    assert validate_response.status_code == HTTPStatus.OK
    assert "Validation success" in validate_response.text

    apply_response = test_client.post("/styles/apply", data=request_payload)
    assert apply_response.status_code == HTTPStatus.OK
    assert "Apply success" in apply_response.text

    page = test_client.get("/styles")
    assert "cinematic" in page.text
    assert "Default title updated" in page.text
    assert "Default instruction updated" in page.text


def test_styles_validate_rejects_missing_default() -> None:
    test_client = TestClient(app)
    request_payload = {
        "styles[0][name]": "fun",
        "styles[0][system]": "default",
        "styles[0][title]": "Fun",
        "styles[0][instruction]": "Add jokes.",
    }
    response = test_client.post("/styles/validate", data=request_payload)

    assert response.status_code == HTTPStatus.OK
    assert "Validation failed" in response.text
    assert "default style is required" in response.text


def test_styles_validate_rejects_default_rename_via_direct_post() -> None:
    test_client = TestClient(app)
    request_payload = {
        "styles[0][name]": "renamed",
        "styles[0][system]": "default",
        "styles[0][title]": "Default",
        "styles[0][instruction]": "",
        "styles[1][name]": "fun",
        "styles[1][title]": "Fun",
        "styles[1][instruction]": "Add jokes.",
    }

    response = test_client.post("/styles/validate", data=request_payload)

    assert response.status_code == HTTPStatus.OK
    assert "Validation failed" in response.text
    assert "default style name cannot be changed" in response.text


def test_legacy_validate_route_still_works() -> None:
    test_client = TestClient(app)
    request_payload = _minimal_valid_payload()

    response = test_client.post("/admin/llm-config/validate", data=request_payload)

    assert response.status_code == HTTPStatus.OK
    assert "Validation success" in response.text


def test_legacy_apply_route_still_works() -> None:
    test_client = TestClient(app)
    request_payload = _minimal_valid_payload()

    response = test_client.post("/admin/llm-config/apply", data=request_payload)

    assert response.status_code == HTTPStatus.OK
    assert "Apply success" in response.text


def test_apply_route_forbidden_outside_local_dev_test(monkeypatch: pytest.MonkeyPatch) -> None:
    test_client = TestClient(app)
    request_payload = _minimal_valid_payload()
    monkeypatch.setattr("app.api.admin_routes.settings.app_env", "prod")

    response = test_client.post("/llm-config/apply", data=request_payload)

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_legacy_apply_route_forbidden_outside_local_dev_test(monkeypatch: pytest.MonkeyPatch) -> None:
    test_client = TestClient(app)
    request_payload = _minimal_valid_payload()
    monkeypatch.setattr("app.api.admin_routes.settings.app_env", "staging")

    response = test_client.post("/admin/llm-config/apply", data=request_payload)

    assert response.status_code == HTTPStatus.FORBIDDEN


def _seed_trace_runs(db_session: Session) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    runs = [
        TraceRun(
            trace_id="trace-1",
            request_id="req-1",
            route="/events/chat_ingest",
            stream_id="stream-a",
            status="success",
            summary="done",
            started_at=base,
            finished_at=base + timedelta(seconds=2),
        ),
        TraceRun(
            trace_id="trace-2",
            request_id="req-2",
            route="/events/chat_reply",
            stream_id="stream-b",
            status="failed",
            error_code="internal_error",
            summary="failed",
            started_at=base + timedelta(minutes=1),
            finished_at=base + timedelta(minutes=1, seconds=1),
        ),
        TraceRun(
            trace_id="trace-3",
            request_id="req-3",
            route="/events/dynamic_prompt",
            stream_id="stream-a",
            status="running",
            started_at=base + timedelta(minutes=2),
            finished_at=None,
        ),
    ]
    db_session.add_all(runs)
    db_session.commit()

    run2 = db_session.query(TraceRun).filter(TraceRun.trace_id == "trace-2").one()
    db_session.add_all(
        [
            TraceEvent(
                trace_run_id=run2.id,
                seq_no=2,
                timestamp=base + timedelta(minutes=1, seconds=2),
                step="request.finish",
                status="failed",
                level="ERROR",
                message="finish",
                payload_json=json.dumps({"error": "[redacted_prompt length=5]"}),
            ),
            TraceEvent(
                trace_run_id=run2.id,
                seq_no=1,
                timestamp=base + timedelta(minutes=1, seconds=1),
                step="request.start",
                status="info",
                level="INFO",
                message="start",
                payload_json=json.dumps({"route": "/events/chat_reply"}),
            ),
        ]
    )
    db_session.commit()


def test_traces_api_runs_returns_newest_first_and_limit(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    _seed_trace_runs(db_session)
    test_client = TestClient(app)

    response = test_client.get("/traces/api/runs", params={"limit": 2})

    assert response.status_code == HTTPStatus.OK
    request_payload = response.json()
    assert [one_item["id"] for one_item in request_payload["items"]] == ["trace-3", "trace-2"]
    assert len(request_payload["items"]) == EXPECTED_RECENT_ITEMS

    app.dependency_overrides.clear()


def test_traces_api_runs_filter_by_stream_id_and_status(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    _seed_trace_runs(db_session)
    test_client = TestClient(app)

    stream_response = test_client.get("/traces/api/runs", params={"stream_id": "stream-a"})
    assert stream_response.status_code == HTTPStatus.OK
    assert [one_item["id"] for one_item in stream_response.json()["items"]] == ["trace-3", "trace-1"]

    status_response = test_client.get("/traces/api/runs", params={"status": "failed"})
    assert status_response.status_code == HTTPStatus.OK
    assert [one_item["id"] for one_item in status_response.json()["items"]] == ["trace-2"]

    app.dependency_overrides.clear()


def test_traces_api_runs_rejects_unknown_status_with_allowed_values(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)

    response = test_client.get("/traces/api/runs", params={"status": "unknown_status"})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    request_payload = response.json()
    assert request_payload["details"]["allowed_statuses"] == list(TRACE_RUN_ALLOWED_STATUSES)

    app.dependency_overrides.clear()


def test_traces_api_run_detail_returns_run_and_ordered_events(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    _seed_trace_runs(db_session)
    test_client = TestClient(app)

    response = test_client.get("/traces/api/runs/trace-2")

    assert response.status_code == HTTPStatus.OK
    request_payload = response.json()
    assert request_payload["run"]["id"] == "trace-2"
    assert "applied_style" not in request_payload["run"]
    assert "requested_style" not in request_payload["run"]
    assert "style_resolution_status" not in request_payload["run"]
    assert [event["seq_no"] for event in request_payload["events"]] == [1, 2]
    assert request_payload["events"][0]["tone"] == "info"
    assert request_payload["events"][0]["style_resolution"] is None
    assert request_payload["events"][1]["tone"] == "failure"
    assert request_payload["events"][1]["payload"]["error"] == "[redacted_prompt length=5]"

    app.dependency_overrides.clear()


def test_traces_api_run_detail_exposes_applied_style_from_event_payload(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)

    run = TraceRun(
        trace_id="trace-style-1",
        request_id="req-style-1",
        route="/events/chat_reply",
        stream_id="stream-style",
        status="success",
        summary="ok",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    db_session.add(
        TraceEvent(
            trace_run_id=run.id,
            seq_no=1,
            timestamp=datetime.now(UTC),
            step="llm.generate.start",
            status="info",
            level="INFO",
            message="start",
            payload_json=json.dumps(
                {
                    "provider": "mock",
                    "requested_style": "random",
                    "applied_style": "absurd",
                    "style_resolution_status": "success",
                    "style_resolution_reason": "random_resolved",
                    "style": "absurd",
                }
            ),
        )
    )
    db_session.commit()

    response = test_client.get("/traces/api/runs/trace-style-1")

    assert response.status_code == HTTPStatus.OK
    request_payload = response.json()
    assert request_payload["run"]["requested_style"] == "random"
    assert request_payload["run"]["applied_style"] == "absurd"
    assert request_payload["run"]["style_resolution_status"] == "success"
    assert request_payload["run"]["style_resolution_reason"] == "random_resolved"
    assert request_payload["events"][0]["payload"]["requested_style"] == "random"
    assert request_payload["events"][0]["payload"]["style"] == "absurd"
    assert request_payload["events"][0]["style_resolution"]["requested"] == "random"
    assert request_payload["events"][0]["style_resolution"]["applied"] == "absurd"
    assert request_payload["events"][0]["style_resolution"]["result"] == "resolved"
    assert request_payload["events"][0]["style_resolution"]["tone"] == "success"

    app.dependency_overrides.clear()


def test_traces_api_run_detail_not_found_returns_404(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)

    response = test_client.get("/traces/api/runs/unknown-run")

    assert response.status_code == HTTPStatus.NOT_FOUND

    app.dependency_overrides.clear()


def test_non_regression_core_routes_still_work(db_session: Session) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)

    assert test_client.get("/playground").status_code == HTTPStatus.OK
    assert test_client.get("/").status_code == HTTPStatus.OK
    assert (
        test_client.get("/debug/context", params={"stream_id": "s", "username": "u", "text": "t"}).status_code
        == HTTPStatus.OK
    )

    event_response = test_client.post(
        "/events/chat_ingest",
        json={"stream_id": "nr", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert event_response.status_code == HTTPStatus.OK

    app.dependency_overrides.clear()


def test_traces_js_contains_style_resolution_block_rendering() -> None:
    script = Path("app/static/admin/traces.js").read_text(encoding="utf-8")
    assert "Style resolution" in script
    assert "requested:" in script
    assert "applied:" in script
    assert "result:" in script
    assert "event.style_resolution" in script


def test_console_css_contains_style_resolution_tones() -> None:
    css = Path("app/static/admin/console.css").read_text(encoding="utf-8")
    assert ".traces-style-resolution--success" in css
    assert ".traces-style-resolution--failure" in css
    assert ".traces-style-resolution--neutral" in css
