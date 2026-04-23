import asyncio
import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Never  # noqa: COP002


if TYPE_CHECKING:
    from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import routes as api_routes
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


REQUEST_ID_HEX_LENGTH = 32


class _Provider:  # noqa: COP012
    def __init__(self, *, fail: bool) -> None:  # noqa: COP006
        self.fail = fail

    async def generate_text(self, **_kwargs: object) -> str:
        if self.fail:
            raise RuntimeError("timeout")
        return "ok"


def _client_with_db(db_session: Session, *, raise_server_exceptions: bool = True) -> TestClient:  # noqa: COP009
    def override_get_db() -> "Generator[Session, None, None]":
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_request_id_header_exists(db_session: Session) -> None:
    client = _client_with_db(db_session, raise_server_exceptions=False)  # noqa: COP005, COP011
    response = client.post(
        "/events/chat_ingest",
        json={"stream_id": "obs_1", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.headers["X-Request-ID"]
    assert len(response.headers["X-Request-ID"]) == REQUEST_ID_HEX_LENGTH
    app.dependency_overrides.clear()


def test_trace_run_success_and_event_order(db_session: Session) -> None:
    client = _client_with_db(db_session, raise_server_exceptions=False)  # noqa: COP005, COP011
    response = client.post(
        "/events/chat_ingest",
        json={"stream_id": "obs_2", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert response.status_code == HTTPStatus.OK

    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))  # noqa: COP005
    assert run is not None
    assert run.status == "success"

    events = list(  # noqa: COP005
        db_session.scalars(
            select(TraceEvent).where(TraceEvent.trace_run_id == run.id).order_by(TraceEvent.seq_no.asc())
        )
    )
    assert events
    assert [e.seq_no for e in events] == sorted(e.seq_no for e in events)  # noqa: COP005, COP015
    app.dependency_overrides.clear()


def test_trace_run_failed_created_on_error(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    async def crash(*_args: object, **_kwargs: object) -> Never:  # noqa: COP007, COP009
        raise RuntimeError("boom")

    monkeypatch.setattr("app.api.routes.service.handle_chat_reply", crash)
    client = _client_with_db(db_session, raise_server_exceptions=False)  # noqa: COP005, COP011
    response = client.post(
        "/events/chat_reply",
        json={"stream_id": "obs_3", "username": "u", "text": "hello", "mentions_bot": False, "role": "viewer"},
    )
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))  # noqa: COP005
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "internal_error"
    app.dependency_overrides.clear()


def test_failed_trace_survives_business_rollback(db_session: Session) -> None:
    start_trace(route="/test", stream_id="obs_4", db=db_session)
    trace_info("request.start", "start")

    db_session.add(ChatMessage(stream_id="obs_4", username="u", role="viewer", text="x", mentions_bot=False))
    db_session.rollback()

    trace_failure("request.finish", "failed", error_code="internal_error")
    finish_trace_failure("internal_error", summary="rolled back")

    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))  # noqa: COP005
    assert run is not None
    assert run.status == "failed"
    assert db_session.scalar(select(ChatMessage).where(ChatMessage.stream_id == "obs_4")) is None


def test_trace_payload_filters_secrets(db_session: Session) -> None:
    start_trace(route="/test", stream_id="obs_5", db=db_session)
    trace_info(
        "safe.payload", "payload", payload={"provider": "mock", "api_key": "secret", "nested": {"token": "x", "ok": 1}}
    )
    finish_trace_success("ok")

    event = db_session.scalar(select(TraceEvent).order_by(TraceEvent.id.desc()))  # noqa: COP005
    assert event is not None
    assert event.payload_json is not None
    payload = json.loads(event.payload_json)  # noqa: COP005
    assert "api_key" not in payload
    assert "token" not in payload.get("nested", {})
    assert payload["provider"] == "mock"


def test_llm_execution_service_trace_events(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = LLMRegistry()
    executor = LLMExecutionService(llm_registry=registry, state_store=ProviderStateStore())
    pool, feature = registry.get_for_feature("chat")

    providers = {"model_a": _Provider(fail=True), "model_b": _Provider(fail=False)}
    monkeypatch.setattr(
        registry,
        "get_provider_instance",
        lambda provider_kind, endpoint: providers[endpoint.name],  # noqa: ARG005
    )

    start_trace(route="/llm", db=db_session)
    reply = asyncio.run(  # noqa: COP005
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
    steps = [  # noqa: COP005
        s
        for s in db_session.scalars(select(TraceEvent.step).order_by(TraceEvent.id.asc())).all()  # noqa: COP005, COP015
        if s.startswith("llm.")
    ]
    assert "llm.generate.start" in steps
    assert "llm.model.failed" in steps
    assert "llm.generate.success" in steps
    events = list(db_session.scalars(select(TraceEvent).order_by(TraceEvent.id.asc())).all())  # noqa: COP005
    start_event = next(event for event in events if event.step == "llm.generate.start")  # noqa: COP005, COP015
    success_event = next(event for event in events if event.step == "llm.generate.success")  # noqa: COP005, COP015
    start_payload = json.loads(start_event.payload_json or "{}")
    success_payload = json.loads(success_event.payload_json or "{}")
    assert start_payload["requested_style"] == feature.style
    assert start_payload["applied_style"] == feature.style
    assert start_payload["style_resolution_status"] == "success"
    assert start_payload["style_resolution_reason"] == "requested_applied"
    assert start_payload["style"] == feature.style
    assert success_payload["requested_style"] == feature.style
    assert success_payload["applied_style"] == feature.style
    assert "system_prompt" not in start_payload
    assert "user_prompt" not in start_payload
    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))  # noqa: COP005
    assert run is not None
    assert run.status == TRACE_RUN_STATUS_SUCCESS


def test_finish_trace_success_marks_degraded_on_llm_pool_exhaustion(db_session: Session) -> None:
    start_trace(route="/events/chat_reply", db=db_session)
    trace_info("request.start", "start")
    trace_failure("llm.model.failed", "model A failed", error_code="llm_error")
    trace_failure("llm.model.failed", "model B failed", error_code="llm_error")
    trace_failure("llm.generate.failed", "all models failed", error_code="llm_error")
    trace_info("dynamic_prompt.fallback", "fallback path selected", payload={"reason": "llm_failed"})
    finish_trace_success("fallback response")

    run = db_session.scalar(select(TraceRun).order_by(TraceRun.id.desc()))  # noqa: COP005
    assert run is not None
    assert run.status == TRACE_RUN_STATUS_DEGRADED
    assert run.status != TRACE_RUN_STATUS_SUCCESS


def test_llm_trace_payload_captures_style_resolution_fields(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = LLMRegistry()
    executor = LLMExecutionService(llm_registry=registry, state_store=ProviderStateStore())
    pool, feature = registry.get_for_feature("chat")
    monkeypatch.setattr(
        registry,
        "get_provider_instance",
        lambda provider_kind, endpoint: _Provider(fail=False),  # noqa: ARG005
    )

    start_trace(route="/llm", db=db_session)
    asyncio.run(
        executor.generate_text_with_pool(
            db=db_session,
            pool=pool,
            feature_settings=feature,
            system_prompt="sys",
            user_prompt="user",
            style_resolution={
                "requested_style": "random",
                "applied_style": "dark",
                "style_resolution_status": "success",
                "style_resolution_reason": "random_resolved",
            },
        )
    )
    finish_trace_success("ok")

    start_event = db_session.scalar(
        select(TraceEvent).where(TraceEvent.step == "llm.generate.start").order_by(TraceEvent.id.desc())
    )
    assert start_event is not None
    payload = json.loads(start_event.payload_json or "{}")  # noqa: COP005
    assert payload["requested_style"] == "random"
    assert payload["applied_style"] == "dark"
    assert payload["style_resolution_status"] == "success"
    assert payload["style_resolution_reason"] == "random_resolved"

    start_trace(route="/llm", db=db_session)
    asyncio.run(
        executor.generate_text_with_pool(
            db=db_session,
            pool=pool,
            feature_settings=feature,
            system_prompt="sys",
            user_prompt="user",
            style_resolution={
                "requested_style": "daark",
                "applied_style": "default",
                "style_resolution_status": "fallback",
                "style_resolution_reason": "style_not_found",
            },
        )
    )
    finish_trace_success("ok")
    fallback_start_event = db_session.scalar(
        select(TraceEvent).where(TraceEvent.step == "llm.generate.start").order_by(TraceEvent.id.desc())
    )
    assert fallback_start_event is not None
    fallback_payload = json.loads(fallback_start_event.payload_json or "{}")
    assert fallback_payload["requested_style"] == "daark"
    assert fallback_payload["applied_style"] == "default"
    assert fallback_payload["style_resolution_status"] == "fallback"
    assert fallback_payload["style_resolution_reason"] == "style_not_found"


def test_dynamic_prompt_service_traces_fallback(db_session: Session) -> None:
    router_service = api_routes.service
    dynamic_service = DynamicPromptService(
        llm_registry=router_service.llm_registry,
        llm_executor=router_service.llm_executor,
        prompts=router_service.prompts,
        style_prompt=router_service.style_prompt,
    )

    start_trace(route="/events/dynamic_prompt", db=db_session)
    result, message = asyncio.run(
        dynamic_service.generate(db=db_session, prompt_name="missing", user="u", data={"x": 1})
    )
    finish_trace_success("fallback")

    assert result == "fallback"
    assert message == ""
    steps = [  # noqa: COP005
        s
        for s in db_session.scalars(select(TraceEvent.step).order_by(TraceEvent.id.asc())).all()  # noqa: COP005, COP015
        if s.startswith("dynamic_prompt.")
    ]
    assert "dynamic_prompt.fallback" in steps


def test_chat_ingest_succeeds_when_trace_start_fails(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode_start_trace(*_args: object, **_kwargs: object) -> Never:  # noqa: COP009
        raise RuntimeError("trace table unavailable")

    monkeypatch.setattr("app.api.routes.start_trace", _explode_start_trace)

    client = _client_with_db(db_session, raise_server_exceptions=False)  # noqa: COP005, COP011
    response = client.post(
        "/events/chat_ingest",
        json={
            "stream_id": "obs_trace_start_fail",
            "username": "u",
            "text": "hello",
            "mentions_bot": False,
            "role": "viewer",
        },
    )
    assert response.status_code == HTTPStatus.OK

    saved = db_session.scalar(  # noqa: COP005
        select(ChatMessage).where(
            ChatMessage.stream_id == "obs_trace_start_fail",
            ChatMessage.username == "u",
            ChatMessage.text == "hello",
        )
    )
    assert saved is not None
    app.dependency_overrides.clear()


def test_chat_ingest_succeeds_when_post_commit_trace_write_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode_trace_success(*_args: object, **_kwargs: object) -> Never:  # noqa: COP009
        raise RuntimeError("trace insert failed")

    monkeypatch.setattr("app.services.router.trace_success", _explode_trace_success)

    client = _client_with_db(db_session, raise_server_exceptions=False)  # noqa: COP005, COP011
    response = client.post(
        "/events/chat_ingest",
        json={
            "stream_id": "obs_trace_post_commit_fail",
            "username": "u",
            "text": "hello",
            "mentions_bot": False,
            "role": "viewer",
        },
    )
    assert response.status_code == HTTPStatus.OK

    saved = db_session.scalar(  # noqa: COP005
        select(ChatMessage).where(
            ChatMessage.stream_id == "obs_trace_post_commit_fail",
            ChatMessage.username == "u",
            ChatMessage.text == "hello",
        )
    )
    assert saved is not None
    app.dependency_overrides.clear()
