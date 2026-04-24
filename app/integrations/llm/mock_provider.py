import typing


@typing.final
class MockProvider:
    async def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_output_tokens: int = 400,
    ) -> str:
        _: typing.Final = (system_prompt, temperature, max_output_tokens)
        return f"[MOCK] {user_prompt[:250]}"
