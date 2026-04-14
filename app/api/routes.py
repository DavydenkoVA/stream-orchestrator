from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.events import ChatEvent
from app.schemas.responses import ChatReply, DebugContextResponse, IngestResponse
from app.services.router import RouterService
from app.schemas.dynamic_prompt import DynamicPromptRequest, DynamicPromptResponse
from app.services.dynamic_prompt_service import DynamicPromptService


router = APIRouter()
service = RouterService()
dynamic_prompt_service = DynamicPromptService(
    llm_registry=service.llm_registry,
    llm_executor=service.llm_executor,
    prompts=service.prompts,
    style_prompt=service.style_prompt,
)

@router.get("/health")
def healthcheck() -> dict:
    return {"ok": True}


@router.post("/events/chat_ingest", response_model=IngestResponse)
def ingest_chat_event(
    payload: ChatEvent,
    db: Session = Depends(get_db),
) -> IngestResponse:
    service.ingest_chat_event(
        db,
        stream_id=payload.stream_id,
        username=payload.username,
        text=payload.text,
        mentions_bot=payload.mentions_bot,
        role=payload.role,
        message_id=payload.message_id,
        reply_to_message_id=payload.reply_to_message_id,
        reply_to_username=payload.reply_to_username,
        reply_to_text=payload.reply_to_text,
    )
    return IngestResponse()


@router.post("/events/chat_reply", response_model=ChatReply)
async def reply_chat_event(
    payload: ChatEvent,
    db: Session = Depends(get_db),
) -> ChatReply:
    reply_text, route = await service.handle_chat_reply(
        db,
        stream_id=payload.stream_id,
        username=payload.username,
        text=payload.text,
        mentions_bot=payload.mentions_bot,
        role=payload.role,
        message_id=payload.message_id,
        reply_to_message_id=payload.reply_to_message_id,
        reply_to_username=payload.reply_to_username,
        reply_to_text=payload.reply_to_text,
    )

    return ChatReply(
        reply_text=reply_text,
        route=route,
        should_reply=bool(reply_text),
    )


@router.get("/debug/prompts/{name}")
def get_prompt(name: str) -> dict:
    from app.prompt_store import PromptStore
    store = PromptStore()
    return {"name": name, "content": store.read(name)}


@router.get("/debug/context", response_model=DebugContextResponse)
def debug_context(
    stream_id: str,
    username: str,
    text: str,
    db: Session = Depends(get_db),
) -> DebugContextResponse:
    normalized_username = service.normalize_username(username)

    global_recent = service.chat_memory.recent_messages(
        db,
        stream_id=stream_id,
    )
    user_recent = service.chat_memory.recent_user_messages(
        db,
        stream_id=stream_id,
        username=normalized_username,
    )
    dialog_recent = service.chat_memory.recent_dialog_messages(
        db,
        stream_id=stream_id,
        username=normalized_username,
    )

    global_recent_block = [f"{m.username} [{m.role}]: {m.text}" for m in global_recent]
    user_recent_block = [f"{m.username} [{m.role}]: {m.text}" for m in user_recent]
    dialog_recent_block = [f"{m.username} [{m.role}]: {m.text}" for m in dialog_recent]

    system_prompt = service.prompts.read("chat_system.txt")
    user_prompt = service.prompts.render(
        "chat_user_template.txt",
        username=username,
        text=text,
        user_recent_block="\n".join(user_recent_block) or "Нет данных.",
        global_recent_block="\n".join(global_recent_block) or "Нет данных.",
        dialog_recent_block="\n".join(dialog_recent_block) or "Нет данных.",
        reply_context_block="Нет",
    )

    return DebugContextResponse(
        global_recent=global_recent_block,
        user_recent=user_recent_block,
        dialog_recent=dialog_recent_block,
        external_context="",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

@router.post("/events/dynamic_prompt", response_model=DynamicPromptResponse)
async def dynamic_prompt_event(
    payload: DynamicPromptRequest,
    db: Session = Depends(get_db),
) -> DynamicPromptResponse:
    result, message = await dynamic_prompt_service.generate(
        db=db,
        prompt_name=payload.prompt,
        user=payload.user,
        data=payload.data,
        llm_provider_override=payload.llm.provider if payload.llm else None,
        style_override=payload.llm.style if payload.llm else None,
        temperature_override=payload.llm.temperature if payload.llm else None,
        max_output_tokens_override=payload.llm.max_output_tokens if payload.llm else None,
    )

    if result != "success":
        message = ""

    return DynamicPromptResponse(result=result, message=message)
