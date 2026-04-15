from __future__ import annotations
from contextvars import ContextVar
from dataclasses import dataclass

from app.observability.trace_recorder import TraceRecorder


@dataclass
class TraceState:
    trace_id: str
    request_id: str
    route: str
    stream_id: str | None
    trace_run_id: int
    recorder: TraceRecorder
    seq_no: int = 0


_trace_ctx: ContextVar[TraceState | None] = ContextVar("trace_state", default=None)


def set_trace_state(state: TraceState) -> None:
    _trace_ctx.set(state)


def get_trace_state() -> TraceState | None:
    return _trace_ctx.get()


def clear_trace_state() -> None:
    _trace_ctx.set(None)
