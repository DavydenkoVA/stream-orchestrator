from __future__ import annotations

from app.config import settings

SUPPORTED_PROVIDER_TYPES: tuple[str, ...] = (
    "openai",
    "mock",
)

SUPPORTED_FEATURE_NAMES: tuple[str, ...] = (
    "chat",
    "dossier",
    "weekly_movies",
    "user_memory",
    "dynamic_prompt",
)

TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 1.0
TEMPERATURE_STEP = 0.01


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
