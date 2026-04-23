from __future__ import annotations
import typing
import uuid


if typing.TYPE_CHECKING:
    from fastapi import Request


REQUEST_ID_STATE_KEY: typing.Final = "request_id"


def generate_request_id() -> str:
    return uuid.uuid4().hex


def set_request_id(http_request: Request, request_identifier: str) -> None:
    http_request.state.request_id = request_identifier


def get_request_id(http_request: Request) -> str:
    request_identifier: typing.Final = getattr(http_request.state, REQUEST_ID_STATE_KEY, "")
    if request_identifier:
        return request_identifier

    fallback_request_id: typing.Final = generate_request_id()
    set_request_id(http_request, fallback_request_id)
    return fallback_request_id
