import re


def strip_basic_markdown(text: str) -> str:
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("`", "")
    return text


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def truncate_for_chat(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    trimmed = text[: limit - 3].rstrip()
    last_space = trimmed.rfind(" ")

    if last_space > max(0, limit // 2):
        trimmed = trimmed[:last_space].rstrip()

    return trimmed + "..."


def prepare_chat_text(text: str, limit: int) -> str:
    text = strip_basic_markdown(text)
    text = normalize_whitespace(text)
    text = truncate_for_chat(text, limit)
    return text