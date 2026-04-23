from __future__ import annotations
import typing

from openai import AsyncOpenAI

from app.integrations.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):  # noqa: COP012
    def __init__(
        self,
        *,
        api_key: str,  # noqa: COP006
        base_url: str,
        model: str,  # noqa: COP006
    ) -> None:
        self.model = model
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
        )

    async def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_output_tokens: int = 400,
    ) -> str:
        response: typing.Final = await self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_output_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        content: typing.Final = response.choices[0].message.content  # noqa: COP005, COP011
        return content or ""
