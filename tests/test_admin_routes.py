from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.chat import ChatMessage
from app.models.trace_event import TraceEvent
from app.models.trace_run import TraceRun


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
    assert "Chat Reply" in response.text
    assert "Dynamic Prompt" in response.text
    assert "Delete test data" in response.text


def test_get_playground_with_dynamic_mode_returns_200() -> None:
    client = TestClient(app)

    response = client.get("/playground", params={"mode": "dynamic"})

    assert response.status_code == 200
    assert "data-initial-mode=\"dynamic\"" in response.text
    assert "Payload template" in response.text
    assert "id=\"dynamic-copy-template-btn\"" in response.text


def test_get_dynamic_prompt_names_endpoint_filters_incomplete_pairs(
    temp_prompts_dir,
) -> None:
    client = TestClient(app)

    dynamic_dir = temp_prompts_dir / "dynamic"
    (dynamic_dir / "weekly_summary_system.txt").write_text("system", encoding="utf-8")
    (dynamic_dir / "weekly_summary_template.txt").write_text("hello {foo}", encoding="utf-8")
    (dynamic_dir / "incomplete_system.txt").write_text("system", encoding="utf-8")

    response = client.get("/playground/api/dynamic-prompts")

    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["test", "weekly_summary"]


def test_get_dynamic_prompt_metadata_returns_full_payload() -> None:
    client = TestClient(app)

    response = client.get("/playground/api/dynamic-prompts/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "test"
    assert payload["required_fields"] == ["loot", "user"]
    assert payload["required_data_fields"] == ["loot"]
    assert payload["data_skeleton"] == {"loot": ""}
    assert payload["system_prompt"] == "dynamic system"
    assert payload["template_prompt"] == "hello {user}, loot={loot}"


def test_reset_stream_deletes_messages_and_is_idempotent(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    db_session.add_all(
        [
            ChatMessage(stream_id="stream_a", username="u1", role="viewer", text="hello", mentions_bot=False),
            ChatMessage(stream_id="stream_a", username="u1", role="bot", text="reply", mentions_bot=False),
            ChatMessage(stream_id="stream_b", username="u2", role="viewer", text="other", mentions_bot=False),
        ]
    )
    db_session.commit()

    context_before = client.get(
        "/debug/context",
        params={"stream_id": "stream_a", "username": "u1", "text": "ping"},
    )
    assert context_before.status_code == 200
    assert len(context_before.json()["global_recent"]) == 2

    first = client.post("/playground/api/chat/reset-stream", json={"stream_id": "stream_a"})
    assert first.status_code == 200
    assert first.json()["deleted"] is True
    assert first.json()["deleted_count"] == 2

    context_after = client.get(
        "/debug/context",
        params={"stream_id": "stream_a", "username": "u1", "text": "ping"},
    )
    assert context_after.status_code == 200
    assert context_after.json()["global_recent"] == []

    second = client.post("/playground/api/chat/reset-stream", json={"stream_id": "stream_a"})
    assert second.status_code == 200
    assert second.json()["deleted"] is True
    assert second.json()["deleted_count"] == 0

    untouched_context = client.get(
        "/debug/context",
        params={"stream_id": "stream_b", "username": "u2", "text": "ping"},
    )
    assert untouched_context.status_code == 200
    assert len(untouched_context.json()["global_recent"]) == 1

    app.dependency_overrides.clear()


def test_reset_stream_rejects_empty_stream_id(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.post("/playground/api/chat/reset-stream", json={"stream_id": ""})

    assert response.status_code == 422

    app.dependency_overrides.clear()


def test_get_dynamic_prompt_metadata_invalid_name_returns_400() -> None:
    client = TestClient(app)

    response = client.get("/playground/api/dynamic-prompts/bad.name")

    assert response.status_code == 400


def test_get_dynamic_prompt_metadata_missing_prompt_returns_404() -> None:
    client = TestClient(app)

    response = client.get("/playground/api/dynamic-prompts/missing")

    assert response.status_code == 404


def test_get_traces_returns_200_with_empty_state() -> None:
    client = TestClient(app)

    response = client.get("/traces")

    assert response.status_code == 200
    assert "Select a trace run to inspect details" in response.text


def test_get_traces_with_run_id_returns_200(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

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

    response = client.get("/traces", params={"run_id": "trace-page-run"})

    assert response.status_code == 200
    assert 'data-selected-run-id="trace-page-run"' in response.text

    app.dependency_overrides.clear()


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


def _seed_trace_runs(db_session) -> None:
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


def test_traces_api_runs_returns_newest_first_and_limit(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    _seed_trace_runs(db_session)
    client = TestClient(app)

    response = client.get("/traces/api/runs", params={"limit": 2})

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["trace-3", "trace-2"]
    assert len(payload["items"]) == 2

    app.dependency_overrides.clear()


def test_traces_api_runs_filter_by_stream_id_and_status(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    _seed_trace_runs(db_session)
    client = TestClient(app)

    stream_response = client.get("/traces/api/runs", params={"stream_id": "stream-a"})
    assert stream_response.status_code == 200
    assert [item["id"] for item in stream_response.json()["items"]] == ["trace-3", "trace-1"]

    status_response = client.get("/traces/api/runs", params={"status": "failed"})
    assert status_response.status_code == 200
    assert [item["id"] for item in status_response.json()["items"]] == ["trace-2"]

    app.dependency_overrides.clear()


def test_traces_api_run_detail_returns_run_and_ordered_events(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    _seed_trace_runs(db_session)
    client = TestClient(app)

    response = client.get("/traces/api/runs/trace-2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == "trace-2"
    assert [event["seq_no"] for event in payload["events"]] == [1, 2]
    assert payload["events"][1]["payload"]["error"] == "[redacted_prompt length=5]"

    app.dependency_overrides.clear()


def test_traces_api_run_detail_not_found_returns_404(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get("/traces/api/runs/unknown-run")

    assert response.status_code == 404

    app.dependency_overrides.clear()


def test_non_regression_core_routes_still_work(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    assert client.get("/playground").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/debug/context", params={"stream_id": "s", "username": "u", "text": "t"}).status_code == 200

    event_response = client.post(
        "/events/chat_ingest",
        json={"stream_id": "nr", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert event_response.status_code == 200

    app.dependency_overrides.clear()
