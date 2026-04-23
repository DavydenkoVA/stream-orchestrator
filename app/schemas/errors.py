from pydantic import BaseModel


class ErrorResponse(BaseModel):  # noqa: COP012
    error_code: str
    message: str
    request_id: str
