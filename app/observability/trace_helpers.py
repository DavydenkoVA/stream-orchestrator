from __future__ import annotations
import typing
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.observability.request_context import get_current_request_id
from app.observability.trace_context import TraceState, clear_trace_state, get_trace_state, set_trace_state
from app.observability.trace_recorder import TraceRecorder
from app.observability.trace_status import TRACE_RUN_STATUS_FAILED


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def start_trace(*, route: str, stream_id: str | None = None, db: Session | None = None) -> str:
    request_id: typing.Final = get_current_request_id() or uuid4().hex
    trace_id: typing.Final = uuid4().hex
    recorder: typing.Final = TraceRecorder.from_db_session(db) if db is not None else TraceRecorder()
    trace_run_id: typing.Final = recorder.start_run(
        trace_id=trace_id,
        request_id=request_id,
        route=route,
        stream_id=stream_id,
    )
    set_trace_state(
        TraceState(
            trace_id=trace_id,
            request_id=request_id,
            route=route,
            stream_id=stream_id,
            trace_run_id=trace_run_id,
            recorder=recorder,
        )
    )
    return trace_id


def trace_info(step: str, message: str, payload: dict[str, Any] | None = None) -> None:
    _append(step=step, status="info", level="INFO", message=message, payload=payload)


def trace_success(step: str, message: str, payload: dict[str, Any] | None = None) -> None:
    _append(step=step, status="success", level="INFO", message=message, payload=payload)


def trace_failure(
    step: str,
    message: str,
    payload: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> None:
    merged: typing.Final = dict(payload or {})
    if error_code:
        merged["error_code"] = error_code
    _append(step=step, status="failed", level="ERROR", message=message, payload=merged or None)


def finish_trace_success(summary: str | None = None) -> None:
    state: typing.Final = get_trace_state()
    if state is None:
        return
    state.recorder.finish_run_success(trace_run_id=state.trace_run_id, summary=summary)
    clear_trace_state()


def finish_trace_failure(error_code: str, summary: str | None = None) -> None:
    state: typing.Final = get_trace_state()
    if state is None:
        return
    state.recorder.finish_run(
        trace_run_id=state.trace_run_id,
        status=TRACE_RUN_STATUS_FAILED,
        error_code=error_code,
        summary=summary,
    )
    clear_trace_state()


def _append(
    *,
    step: str,
    status: str,
    level: str,
    message: str,
    payload: dict[str, Any] | None,
) -> None:
    state: typing.Final = get_trace_state()
    if state is None:
        return
    state.seq_no += 1
    state.recorder.append_event(
        trace_run_id=state.trace_run_id,
        seq_no=state.seq_no,
        step=step,
        status=status,
        level=level,
        message=message,
        payload=payload,
    )
