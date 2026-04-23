import typing


@typing.final
class MemoryItemPayload(typing.TypedDict):
    text: str  # noqa: COP004


@typing.final
class DossierContextPayload(typing.TypedDict):
    username: str
    memory_items: list[MemoryItemPayload]


@typing.final
class LLMClient:
    def generate_chat_reply(self, *, username: str, input_text: str, _recent_messages: list[str]) -> str:
        return f"[{username}] заглушка ответа: {input_text}"

    def generate_dossier(self, dossier_context: DossierContextPayload) -> str:
        username: typing.Final = dossier_context["username"]
        memory_items: typing.Final = dossier_context["memory_items"][:3]
        if not memory_items:
            return f"На @{username} пока мало данных. Нужна история чата."  # noqa: RUF001
        memory_bullets: typing.Final = "; ".join(one_item["text"] for one_item in memory_items)  # noqa: COP011
        return f"Досье на @{username}: {memory_bullets}."
