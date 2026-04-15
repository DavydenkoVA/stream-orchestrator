import asyncio
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models.chat import ChatMessage
from app.models.trace_event import TraceEvent
from app.models.trace_run import TraceRun
from app.observability.trace_helpers import (
    finish_trace_failure,
    finish_trace_success,
    start_trace,
    trace_failure,
    trace_info,
)
from app.observability.trace_status import TRACE_RUN_STATUS_DEGRADED, TRACE_RUN_STATUS_SUCCESS
from app.services.dynamic_prompt_service import DynamicPromptService
from app.services.llm_execution_service import LLMExecutionService
from app.services.llm_registry import LLMRegistry
from app.services.provider_state_store import ProviderStateStore
from app.api import routes as api_routes


class _Provider:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail

    async def generate_text(self, **kwargs) -> str:
        if self.fail:
            raise RuntimeError("timeout")
        return "ok"


def _client_with_db(db_session, *, raise_server_exceptions: bool = True):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_request_id_header_exists(db_session) -> None:
    client = _client_with_db(db_session, raise_server_exceptions=False)
    response = client.post(
        "/events/chat_ingest",
        json={"stream_id": "obs_1", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert len(response.headers["X-Request-ID"]) == 32
    app.dependency_overrides.clear()


def test_trace_run_success_and_event_order(db_session) -> None:
    client = _client_with_db(db_session, raise_server_exceptions=False)
    response = client.post(
        "/events/chat_ingest",
        json={"stream_id": "obs_2", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert response.status_code == 200

    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))
    assert run is not None
    assert run.status == "success"

    events = list(db_session.scalars(select(TraceEvent).where(TraceEvent.trace_run_id == run.id).order_by(TraceEvent.seq_no.asc())))
    assert events
    assert [e.seq_no for e in events] == sorted(e.seq_no for e in events)
    app.dependency_overrides.clear()


def test_trace_run_failed_created_on_error(db_session, monkeypatch) -> None:
    async def crash(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.api.routes.service.handle_chat_reply", crash)
    client = _client_with_db(db_session, raise_server_exceptions=False)
    response = client.post(
        "/events/chat_reply",
        json={"stream_id": "obs_3", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert response.status_code == 500

    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "internal_error"
    app.dependency_overrides.clear()


def test_failed_trace_survives_business_rollback(db_session) -> None:
    start_trace(route="/test", stream_id="obs_4", db=db_session)
    trace_info("request.start", "start")

    db_session.add(ChatMessage(stream_id="obs_4", username="u", role="viewer", text="x", mentions_bot=False))
    db_session.rollback()

    trace_failure("request.finish", "failed", error_code="internal_error")
    finish_trace_failure("internal_error", summary="rolled back")

    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))
    assert run is not None
    assert run.status == "failed"
    assert db_session.scalar(select(ChatMessage).where(ChatMessage.stream_id == "obs_4")) is None


def test_trace_payload_filters_secrets(db_session) -> None:
    start_trace(route="/test", stream_id="obs_5", db=db_session)
    trace_info("safe.payload", "payload", payload={"provider": "mock", "api_key": "secret", "nested": {"token": "x", "ok": 1}})
    finish_trace_success("ok")

    event = db_session.scalar(select(TraceEvent).order_by(TraceEvent.id.desc()))
    assert event is not None
    payload = json.loads(event.payload_json)
    assert "api_key" not in payload
    assert "token" not in payload.get("nested", {})
    assert payload["provider"] == "mock"


def test_llm_execution_service_trace_events(db_session, monkeypatch) -> None:
    registry = LLMRegistry()
    executor = LLMExecutionService(llm_registry=registry, state_store=ProviderStateStore())
    pool, feature = registry.get_for_feature("chat")

    providers = {"model_a": _Provider(fail=True), "model_b": _Provider(fail=False)}
    monkeypatch.setattr(registry, "get_provider_instance", lambda provider_kind, endpoint: providers[endpoint.name])

    start_trace(route="/llm", db=db_session)
    reply = asyncio.run(
        executor.generate_text_with_pool(
            db=db_session,
            pool=pool,
            feature_settings=feature,
            system_prompt="sys",
            user_prompt="user",
        )
    )
    finish_trace_success("ok")

    assert reply == "ok"
    steps = [
        s
        for s in db_session.scalars(select(TraceEvent.step).order_by(TraceEvent.id.asc())).all()
        if s.startswith("llm.")
    ]
    assert "llm.generate.start" in steps
    assert "llm.model.failed" in steps
    assert "llm.generate.success" in steps
    events = list(db_session.scalars(select(TraceEvent).order_by(TraceEvent.id.asc())).all())
    start_event = next(event for event in events if event.step == "llm.generate.start")
    success_event = next(event for event in events if event.step == "llm.generate.success")
    start_payload = json.loads(start_event.payload_json or "{}")
    success_payload = json.loads(success_event.payload_json or "{}")
    assert start_payload["style"] == feature.style
    assert success_payload["style"] == feature.style
    assert "system_prompt" not in start_payload
    assert "user_prompt" not in start_payload
    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))
    assert run is not None
    assert run.status == TRACE_RUN_STATUS_SUCCESS


def test_finish_trace_success_marks_degraded_on_llm_pool_exhaustion(db_session) -> None:
    start_trace(route="/events/chat_reply", db=db_session)
    trace_info("request.start", "start")
    trace_failure("llm.model.failed", "model A failed", error_code="llm_error")
    trace_failure("llm.model.failed", "model B failed", error_code="llm_error")
    trace_failure("llm.generate.failed", "all models failed", error_code="llm_error")
    trace_info("dynamic_prompt.fallback", "fallback path selected", payload={"reason": "llm_failed"})
    finish_trace_success("fallback response")

    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))
    assert run is not None
    assert run.status == TRACE_RUN_STATUS_DEGRADED
    assert run.status != TRACE_RUN_STATUS_SUCCESS


def test_dynamic_prompt_service_traces_fallback(db_session) -> None:
    router_service = api_routes.service
    dynamic_service = DynamicPromptService(
        llm_registry=router_service.llm_registry,
        llm_executor=router_service.llm_executor,
        prompts=router_service.prompts,
        style_prompt=router_service.style_prompt,
    )

    start_trace(route="/events/dynamic_prompt", db=db_session)
    result, message = asyncio.run(dynamic_service.generate(db=db_session, prompt_name="missing", user="u", data={"x": 1}))
    finish_trace_success("fallback")

    assert result == "fallback"
    assert message == ""
    steps = [
        s
        for s in db_session.scalars(select(TraceEvent.step).order_by(TraceEvent.id.asc())).all()
        if s.startswith("dynamic_prompt.")
    ]
    assert "dynamic_prompt.fallback" in steps


def test_chat_ingest_succeeds_when_trace_start_fails(db_session, monkeypatch) -> None:
    def _explode_start_trace(*args, **kwargs):
        raise RuntimeError("trace table unavailable")

    monkeypatch.setattr("app.api.routes.start_trace", _explode_start_trace)

    client = _client_with_db(db_session, raise_server_exceptions=False)
    response = client.post(
        "/events/chat_ingest",
        json={"stream_id": "obs_trace_start_fail", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert response.status_code == 200

    saved = db_session.scalar(
        select(ChatMessage).where(
            ChatMessage.stream_id == "obs_trace_start_fail",
            ChatMessage.username == "u",
            ChatMessage.text == "hello",
        )
    )
    assert saved is not None
    app.dependency_overrides.clear()


def test_chat_ingest_succeeds_when_post_commit_trace_write_fails(db_session, monkeypatch) -> None:
    def _explode_trace_success(*args, **kwargs):
        raise RuntimeError("trace insert failed")

    monkeypatch.setattr("app.services.router.trace_success", _explode_trace_success)

    client = _client_with_db(db_session, raise_server_exceptions=False)
    response = client.post(
        "/events/chat_ingest",
        json={"stream_id": "obs_trace_post_commit_fail", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert response.status_code == 200

    saved = db_session.scalar(
        select(ChatMessage).where(
            ChatMessage.stream_id == "obs_trace_post_commit_fail",
            ChatMessage.username == "u",
            ChatMessage.text == "hello",
        )
    )
    assert saved is not None
    app.dependency_overrides.clear()
