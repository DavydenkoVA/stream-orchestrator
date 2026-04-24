import typing

from pydantic import BaseModel


@typing.final
class ErrorResponse(BaseModel):
    error_code: str
    message: str
    request_id: str
