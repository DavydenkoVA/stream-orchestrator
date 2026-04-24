from __future__ import annotations
import typing

from pydantic import BaseModel, Field, field_validator

from app.services.llm_config_source import TEMPERATURE_MAX, TEMPERATURE_MIN


@typing.final
class DynamicPromptLLMOverride(BaseModel):
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    style: str | None = Field(default=None, min_length=1, max_length=64)
    temperature: float | None = None
    max_output_tokens: int | None = None

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < TEMPERATURE_MIN or value > TEMPERATURE_MAX:
            raise ValueError("invalid temperature")
        return value

    @field_validator("max_output_tokens")
    @classmethod
    def validate_max_tokens(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("invalid max_output_tokens")
        return value


@typing.final
class DynamicPromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=64)
    user: str = Field(..., min_length=1, max_length=64)
    data: dict[str, typing.Any]
    llm: DynamicPromptLLMOverride | None = None


@typing.final
class DynamicPromptResponse(BaseModel):
    result: str
    message: str
