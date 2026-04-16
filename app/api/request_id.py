from __future__ import annotations
import typing
from typing import TYPE_CHECKING
from uuid import uuid4


if TYPE_CHECKING:
    from fastapi import Request


REQUEST_ID_STATE_KEY: typing.Final = "request_id"


def generate_request_id() -> str:
    return uuid4().hex


def set_request_id(request: Request, request_id: str) -> None:
    request.state.request_id = request_id


def get_request_id(request: Request) -> str:
    request_id: typing.Final = getattr(request.state, REQUEST_ID_STATE_KEY, "")
    if request_id:
        return request_id

    fallback_request_id: typing.Final = generate_request_id()
    set_request_id(request, fallback_request_id)
    return fallback_request_id
