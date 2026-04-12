from __future__ import annotations

from app.config import settings
from app.integrations.llm.base import LLMProvider
from app.integrations.llm.mock_provider import MockProvider
from app.integrations.llm.openai_provider import OpenAIProvider


def build_llm_provider() -> LLMProvider:
    return build_llm_provider_from_config(
        provider_name=settings.llm_provider,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )


def build_llm_provider_from_config(
    *,
    provider_name: str,
    api_key: str,
    base_url: str,
    model: str,
) -> LLMProvider:
    normalized = provider_name.strip().lower()

    if normalized == "mock":
        return MockProvider()

    if normalized == "openai":
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

    raise ValueError(f"Unsupported llm provider: {provider_name}")