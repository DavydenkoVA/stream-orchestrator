from app.config import settings
from app.integrations.llm.base import LLMProvider
from app.integrations.llm.mock_provider import MockProvider
from app.integrations.llm.openai_provider import OpenAIProvider


def build_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.strip().lower()

    if provider == "mock":
        return MockProvider()

    if provider == "openai":
        return OpenAIProvider()

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")