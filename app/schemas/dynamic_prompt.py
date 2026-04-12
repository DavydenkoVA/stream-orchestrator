from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DynamicPromptLLMOverride(BaseModel):
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    temperature: float | None = None
    max_output_tokens: int | None = None


class DynamicPromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=64)
    user: str = Field(..., min_length=1, max_length=64)
    data: dict[str, Any]
    llm: DynamicPromptLLMOverride | None = None


class DynamicPromptResponse(BaseModel):
    result: str
    message: str