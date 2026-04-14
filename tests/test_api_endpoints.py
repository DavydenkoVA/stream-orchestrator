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
