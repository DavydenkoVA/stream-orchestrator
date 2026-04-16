from __future__ import annotations
import typing

from app.config import settings


SUPPORTED_PROVIDER_TYPES: typing.Final[tuple[str, ...]] = (
    "openai",
    "mock",
)

SUPPORTED_FEATURE_NAMES: typing.Final[tuple[str, ...]] = (
    "chat",
    "dossier",
    "weekly_movies",
    "user_memory",
    "dynamic_prompt",
)

TEMPERATURE_MIN: typing.Final = 0.0
TEMPERATURE_MAX: typing.Final = 1.0
TEMPERATURE_STEP: typing.Final = 0.01


def default_feature_settings() -> dict[str, dict[str, float | int | str | None]]:
    return {
        feature_name: {
            "provider": None,
            "temperature": settings.llm_temperature,
            "max_output_tokens": settings.llm_max_output_tokens,
            "style": "default",
        }
        for feature_name in SUPPORTED_FEATURE_NAMES
    }
