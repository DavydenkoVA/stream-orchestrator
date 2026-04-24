import typing

from pydantic import BaseModel, Field


@typing.final
class ChatEvent(BaseModel):
    stream_id: str = Field(min_length=1)
    username: str = Field(min_length=1)
    text: str = Field(min_length=1)
    mentions_bot: bool = False

    role: typing.Literal["viewer", "bot", "broadcaster", "system"] = "viewer"

    channel: str | None = None
    message_id: str | None = None

    reply_to_message_id: str | None = None
    reply_to_username: str | None = None
    reply_to_text: str | None = None

    is_mod: bool = False
    is_broadcaster: bool = False
