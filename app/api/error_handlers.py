from __future__ import annotations
import logging
import types
import typing

from fastapi.responses import JSONResponse

from app.api.request_id import get_request_id
from app.schemas.errors import ErrorResponse


if typing.TYPE_CHECKING:
    from fastapi import HTTPException, Request
    from fastapi.exceptions import RequestValidationError


logger_instance = logging.getLogger(__name__)


_ERROR_MESSAGES_BY_STATUS: typing.Final = types.MappingProxyType(
    {
        400: ("bad_request", "Bad request"),
        404: ("not_found", "Not found"),
    }
)


def build_error_payload(
    error_code: str,
    error_message: str,
    request_identifier: str,
    *,
    error_details: dict[str, object] | None = None,
) -> dict[str, object]:
    response_payload: typing.Final[dict[str, object]] = ErrorResponse(
        error_code=error_code,
        message=error_message,
        request_id=request_identifier,
    ).model_dump()
    if error_details:
        response_payload["details"] = error_details
    return response_payload


async def handle_validation_exception(
    http_request: Request,
    validation_exception: RequestValidationError,
) -> JSONResponse:
    request_identifier: typing.Final = get_request_id(http_request)
    logger_instance.warning(
        "Validation error: request_id=%s method=%s path=%s errors=%s",
        request_identifier,
        http_request.method,
        http_request.url.path,
        validation_exception.errors(),
    )
    return JSONResponse(
        status_code=422,
        content=build_error_payload(
            error_code="validation_error",
            error_message="Validation error",
            request_identifier=request_identifier,
        ),
    )


async def handle_http_exception(http_request: Request, http_exception: HTTPException) -> JSONResponse:
    request_identifier: typing.Final = get_request_id(http_request)

    error_code, error_message = _ERROR_MESSAGES_BY_STATUS.get(
        http_exception.status_code,
        ("internal_error", "Internal server error"),
    )

    logger_instance.warning(
        "HTTP exception: request_id=%s method=%s path=%s status=%s exception_type=%s",
        request_identifier,
        http_request.method,
        http_request.url.path,
        http_exception.status_code,
        type(http_exception).__name__,
    )

    return JSONResponse(
        status_code=http_exception.status_code,
        content=build_error_payload(
            error_code=error_code,
            error_message=error_message,
            request_identifier=request_identifier,
            error_details=http_exception.detail if isinstance(http_exception.detail, dict) else None,
        ),
    )


async def handle_unhandled_exception(http_request: Request, exception_obj: Exception) -> JSONResponse:
    request_identifier: typing.Final = get_request_id(http_request)
    logger_instance.exception(
        "Unhandled exception: request_id=%s method=%s path=%s exception_type=%s",
        request_identifier,
        http_request.method,
        http_request.url.path,
        type(exception_obj).__name__,
    )
    return JSONResponse(
        status_code=500,
        content=build_error_payload(
            error_code="internal_error",
            error_message="Internal server error",
            request_identifier=request_identifier,
        ),
    )
