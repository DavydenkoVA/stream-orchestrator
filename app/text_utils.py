import re
import typing


def strip_basic_markdown(text: str) -> str:  # noqa: COP006, COP009
    text = text.replace("**", "")  # noqa: COP005
    text = text.replace("__", "")  # noqa: COP005
    return text.replace("`", "")


def normalize_whitespace(text: str) -> str:  # noqa: COP006, COP009
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # noqa: COP005
    text = re.sub(r"\n{3,}", "\n\n", text)  # noqa: COP005
    text = re.sub(r"[ \t]{2,}", " ", text)  # noqa: COP005
    return text.strip()


def truncate_for_chat(text: str, limit: int) -> str:  # noqa: COP006, COP009
    if len(text) <= limit:
        return text

    trimmed = text[: limit - 3].rstrip()  # noqa: COP005
    last_space: typing.Final = trimmed.rfind(" ")

    if last_space > max(0, limit // 2):
        trimmed = trimmed[:last_space].rstrip()  # noqa: COP005

    return trimmed + "..."


def prepare_chat_text(text: str, limit: int) -> str:  # noqa: COP006
    text = strip_basic_markdown(text)  # noqa: COP005
    text = normalize_whitespace(text)  # noqa: COP005
    return truncate_for_chat(text, limit)
