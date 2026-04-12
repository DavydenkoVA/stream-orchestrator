from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DynamicPromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=64)
    user: str = Field(..., min_length=1, max_length=64)
    data: dict[str, Any]


class DynamicPromptResponse(BaseModel):
    result: str
    message: str