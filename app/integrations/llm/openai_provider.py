import logging

import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class OpenAIProvider:
    def __init__(self) -> None:
        timeout = httpx.Timeout(settings.llm_timeout_seconds)
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or None,
            timeout=timeout,
        )

    async def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_output_tokens: int = 400,
    ) -> str:
        logger.info(
            "LLM request: model=%s prompt_len=%s max_tokens=%s",
            settings.llm_model,
            len(user_prompt),
            max_output_tokens,
        )

        response = await self.client.responses.create(
            model=settings.llm_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        text = getattr(response, "output_text", None)
        if text:
            logger.info("LLM response ok: output_len=%s", len(text))
            return text.strip()

        logger.warning("LLM response empty")
        return "[LLM] Пустой ответ от модели."