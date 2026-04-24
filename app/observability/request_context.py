from __future__ import annotations
import contextvars


_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def set_current_request_id(request_id: str) -> None:
    _request_id_ctx.set(request_id)


def get_current_request_id() -> str | None:
    return _request_id_ctx.get()


def clear_current_request_id() -> None:
    _request_id_ctx.set(None)
