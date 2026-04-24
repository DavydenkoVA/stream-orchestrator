from __future__ import annotations
import contextvars
import dataclasses
import typing


if typing.TYPE_CHECKING:
    from app.observability.trace_recorder import TraceRecorder


@dataclasses.dataclass
@typing.final
class TraceState:  # noqa: COP014
    trace_id: str
    request_id: str
    route: str  # noqa: COP004
    stream_id: str | None
    trace_run_id: int
    recorder: TraceRecorder
    seq_no: int = 0  # noqa: COP004


_trace_ctx: contextvars.ContextVar[TraceState | None] = contextvars.ContextVar("trace_state", default=None)


def set_trace_state(state: TraceState) -> None:  # noqa: COP006
    _trace_ctx.set(state)


def get_trace_state() -> TraceState | None:
    return _trace_ctx.get()


def clear_trace_state() -> None:
    _trace_ctx.set(None)
