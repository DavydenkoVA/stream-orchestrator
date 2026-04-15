import re

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app


def test_chat_ingest_and_chat_reply_and_ignore_bot(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    ingest_payload = {
        "stream_id": "s1",
        "username": "Viewer_1",
        "text": "hello",
        "mentions_bot": False,
        "role": "viewer",
    }

    ingest_response = client.post("/events/chat_ingest", json=ingest_payload)
    assert ingest_response.status_code == 200
    assert ingest_response.json()["stored"] is True

    bot_payload = {
        "stream_id": "s1",
        "username": "stream_bot",
        "text": "service",
        "mentions_bot": False,
        "role": "bot",
    }

    bot_response = client.post("/events/chat_reply", json=bot_payload)
    assert bot_response.status_code == 200
    assert bot_response.json()["route"] == "ignored"
    assert bot_response.json()["should_reply"] is False
    trace_id = bot_response.headers.get("X-Trace-Id")
    assert trace_id
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id)

    app.dependency_overrides.clear()


def test_chat_reply_routes_dossier_and_weekly_movies(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    dossier_response = client.post(
        "/events/chat_reply",
        json={
            "stream_id": "s2",
            "username": "viewer",
            "text": "досье на @target_user",
            "mentions_bot": False,
            "role": "viewer",
        },
    )
    assert dossier_response.status_code == 200
    assert dossier_response.json()["route"] == "dossier"

    weekly_response = client.post(
        "/events/chat_reply",
        json={
            "stream_id": "s2",
            "username": "viewer",
            "text": "что смотрим на этой неделе?",
            "mentions_bot": False,
            "role": "viewer",
        },
    )
    assert weekly_response.status_code == 200
    assert weekly_response.json()["route"] == "weekly_movies"

    app.dependency_overrides.clear()


def test_dynamic_prompt_endpoint_returns_success_and_fallback(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    success_response = client.post(
        "/events/dynamic_prompt",
        json={
            "prompt": "test",
            "user": "alice",
            "data": {"loot": "ring"},
        },
    )
    assert success_response.status_code == 200
    assert success_response.json()["result"] == "success"
    success_trace_id = success_response.headers.get("X-Trace-Id")
    assert success_trace_id
    assert re.fullmatch(r"[0-9a-f]{32}", success_trace_id)

    fallback_response = client.post(
        "/events/dynamic_prompt",
        json={
            "prompt": "missing_prompt",
            "user": "alice",
            "data": {"loot": "ring"},
        },
    )
    assert fallback_response.status_code == 200
    assert fallback_response.json()["result"] == "fallback"
    fallback_trace_id = fallback_response.headers.get("X-Trace-Id")
    assert fallback_trace_id
    assert re.fullmatch(r"[0-9a-f]{32}", fallback_trace_id)

    app.dependency_overrides.clear()


def test_dynamic_prompt_override_temperature_out_of_range_returns_422(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.post(
        "/events/dynamic_prompt",
        json={
            "prompt": "test",
            "user": "alice",
            "data": {"loot": "ring"},
            "llm": {"temperature": 1.2},
        },
    )

    assert response.status_code == 422

    app.dependency_overrides.clear()


def test_debug_context_endpoint(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    client.post(
        "/events/chat_ingest",
        json={
            "stream_id": "s3",
            "username": "alice",
            "text": "привет",
            "mentions_bot": False,
            "role": "viewer",
        },
    )

    response = client.get(
        "/debug/context",
        params={
            "stream_id": "s3",
            "username": "alice",
            "text": "@bot как дела?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "debug_context"
    assert isinstance(payload["global_recent"], list)
    assert payload["system_prompt"]
    assert payload["user_prompt"]

    app.dependency_overrides.clear()


def test_chat_reply_unhandled_exception_is_sanitized(db_session, monkeypatch) -> None:
    def override_get_db():
        yield db_session

    async def crash(*args, **kwargs):
        raise RuntimeError("provider_key=secret-key stack exploded")

    monkeypatch.setattr("app.api.routes.service.handle_chat_reply", crash)

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/events/chat_reply",
        json={
            "stream_id": "s_err",
            "username": "viewer",
            "text": "hello",
            "mentions_bot": False,
            "role": "viewer",
        },
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == "internal_error"
    assert payload["message"] == "Internal server error"
    assert payload["request_id"]
    assert len(payload["request_id"]) == 32
    assert "RuntimeError" not in response.text
    assert "secret-key" not in response.text

    app.dependency_overrides.clear()


def test_chat_reply_validation_error_is_normalized(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.post(
        "/events/chat_reply",
        json={
            "stream_id": "s_validation",
            "username": "viewer",
            "mentions_bot": False,
            "role": "viewer",
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == "validation_error"
    assert payload["message"] == "Validation error"
    assert payload["request_id"]

    app.dependency_overrides.clear()


def test_chat_reply_http_exception_is_sanitized(db_session, monkeypatch) -> None:
    def override_get_db():
        yield db_session

    async def fail_with_http(*args, **kwargs):
        raise HTTPException(status_code=400, detail="internal failure details should stay private")

    monkeypatch.setattr("app.api.routes.service.handle_chat_reply", fail_with_http)

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.post(
        "/events/chat_reply",
        json={
            "stream_id": "s_http",
            "username": "viewer",
            "text": "hello",
            "mentions_bot": False,
            "role": "viewer",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "bad_request"
    assert payload["message"] == "Bad request"
    assert payload["request_id"]
    assert "internal failure details" not in response.text

    app.dependency_overrides.clear()


def test_debug_prompts_endpoint(db_session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get("/debug/prompts/chat_system.txt")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "chat_system.txt"
    assert payload["content"]

    app.dependency_overrides.clear()
