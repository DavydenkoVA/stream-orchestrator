from __future__ import annotations
import typing
import uuid

from app.observability.request_context import get_current_request_id
from app.observability.trace_context import TraceState, clear_trace_state, get_trace_state, set_trace_state
from app.observability.trace_recorder import TraceRecorder
from app.observability.trace_status import TRACE_RUN_STATUS_FAILED


if typing.TYPE_CHECKING:
    from sqlalchemy.orm import Session


def start_trace(*, route: str, stream_id: str | None = None, db: Session | None = None) -> str:  # noqa: COP006
    request_id: typing.Final = get_current_request_id() or uuid.uuid4().hex
    trace_id: typing.Final = uuid.uuid4().hex
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


def trace_info(step: str, message: str, payload: dict[str, typing.Any] | None = None) -> None:  # noqa: COP006, COP009
    _append(step=step, status="info", level="INFO", message=message, payload=payload)


def trace_success(step: str, message: str, payload: dict[str, typing.Any] | None = None) -> None:  # noqa: COP006, COP009
    _append(step=step, status="success", level="INFO", message=message, payload=payload)


def trace_failure(  # noqa: COP009
    step: str,  # noqa: COP006
    message: str,  # noqa: COP006
    payload: dict[str, typing.Any] | None = None,  # noqa: COP006
    error_code: str | None = None,
) -> None:
    merged: typing.Final = dict(payload or {})  # noqa: COP005
    if error_code:
        merged["error_code"] = error_code
    _append(step=step, status="failed", level="ERROR", message=message, payload=merged or None)


def finish_trace_success(summary: str | None = None) -> None:  # noqa: COP006, COP009
    state: typing.Final = get_trace_state()  # noqa: COP005
    if state is None:
        return
    state.recorder.finish_run_success(trace_run_id=state.trace_run_id, summary=summary)
    clear_trace_state()


def finish_trace_failure(error_code: str, summary: str | None = None) -> None:  # noqa: COP006, COP009
    state: typing.Final = get_trace_state()  # noqa: COP005
    if state is None:
        return
    state.recorder.finish_run(
        trace_run_id=state.trace_run_id,
        status=TRACE_RUN_STATUS_FAILED,
        error_code=error_code,
        summary=summary,
    )
    clear_trace_state()


def _append(  # noqa: COP009
    *,
    step: str,  # noqa: COP006
    status: str,  # noqa: COP006
    level: str,  # noqa: COP006
    message: str,  # noqa: COP006
    payload: dict[str, typing.Any] | None,  # noqa: COP006
) -> None:
    state: typing.Final = get_trace_state()  # noqa: COP005
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
