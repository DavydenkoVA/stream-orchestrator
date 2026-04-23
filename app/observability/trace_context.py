from __future__ import annotations
from contextvars import ContextVar  # noqa: COP002
from dataclasses import dataclass  # noqa: COP002
from typing import TYPE_CHECKING  # noqa: COP002


if TYPE_CHECKING:
    from app.observability.trace_recorder import TraceRecorder


@dataclass
class TraceState:  # noqa: COP012, COP014
    trace_id: str
    request_id: str
    route: str  # noqa: COP004
    stream_id: str | None
    trace_run_id: int
    recorder: TraceRecorder
    seq_no: int = 0  # noqa: COP004


_trace_ctx: ContextVar[TraceState | None] = ContextVar("trace_state", default=None)


def set_trace_state(state: TraceState) -> None:  # noqa: COP006
    _trace_ctx.set(state)


def get_trace_state() -> TraceState | None:
    return _trace_ctx.get()


def clear_trace_state() -> None:
    _trace_ctx.set(None)
