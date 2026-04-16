from __future__ import annotations
import logging
import typing
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from app.api.request_id import get_request_id
from app.schemas.errors import ErrorResponse


if TYPE_CHECKING:
    from fastapi import HTTPException, Request
    from fastapi.exceptions import RequestValidationError


logger = logging.getLogger(__name__)


_ERROR_MESSAGES_BY_STATUS: typing.Final = {
    400: ("bad_request", "Bad request"),
    404: ("not_found", "Not found"),
}


def _error_payload(
    error_code: str,
    message: str,
    request_id: str,
    *,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: typing.Final[dict[str, object]] = ErrorResponse(
        error_code=error_code,
        message=message,
        request_id=request_id,
    ).model_dump()
    if details:
        payload["details"] = details
    return payload


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id: typing.Final = get_request_id(request)
    logger.warning(
        "Validation error: request_id=%s method=%s path=%s errors=%s",
        request_id,
        request.method,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            error_code="validation_error",
            message="Validation error",
            request_id=request_id,
        ),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id: typing.Final = get_request_id(request)

    error_code, message = _ERROR_MESSAGES_BY_STATUS.get(
        exc.status_code,
        ("internal_error", "Internal server error"),
    )

    logger.warning(
        "HTTP exception: request_id=%s method=%s path=%s status=%s exception_type=%s",
        request_id,
        request.method,
        request.url.path,
        exc.status_code,
        type(exc).__name__,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            error_code=error_code,
            message=message,
            request_id=request_id,
            details=exc.detail if isinstance(exc.detail, dict) else None,
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id: typing.Final = get_request_id(request)
    logger.exception(
        "Unhandled exception: request_id=%s method=%s path=%s exception_type=%s",
        request_id,
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            error_code="internal_error",
            message="Internal server error",
            request_id=request_id,
        ),
    )
