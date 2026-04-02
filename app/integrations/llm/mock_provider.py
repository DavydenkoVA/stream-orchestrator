class MockProvider:
    async def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_output_tokens: int = 400,
    ) -> str:
        return f"[MOCK] {user_prompt[:250]}"
