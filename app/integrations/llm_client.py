class LLMClient:
    def generate_chat_reply(self, *, username: str, text: str, recent_messages: list[str]) -> str:
        return f"[{username}] заглушка ответа: {text}"

    def generate_dossier(self, context: dict) -> str:
        username = context["username"]
        memory_items = context["memory_items"][:3]
        if not memory_items:
            return f"На @{username} пока мало данных. Нужна история чата."
        bullets = "; ".join(item["text"] for item in memory_items)
        return f"Досье на @{username}: {bullets}."
