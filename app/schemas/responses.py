import typing

from pydantic import BaseModel


@typing.final
class ChatReply(BaseModel):
    ok: bool = True
    reply_text: str
    route: str
    should_reply: bool = True


@typing.final
class IngestResponse(BaseModel):
    ok: bool = True
    stored: bool = True
    route: str = "ingest"


@typing.final
class DebugContextResponse(BaseModel):
    ok: bool = True
    route: str = "debug_context"
    global_recent: list[str]
    user_recent: list[str]
    dialog_recent: list[str]
    external_context: str
    system_prompt: str
    user_prompt: str
