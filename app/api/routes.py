import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.events import ChatEvent
from app.schemas.responses import ChatReply, DebugContextResponse, IngestResponse
from app.services.router import RouterService
from app.schemas.dynamic_prompt import DynamicPromptRequest, DynamicPromptResponse
from app.services.dynamic_prompt_service import DynamicPromptService

logger = logging.getLogger(__name__)

router = APIRouter()
service = RouterService()
dynamic_prompt_service = DynamicPromptService(
    llm=service.llm,
    prompts=service.prompts,
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
    try:
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
    except Exception as e:
        logger.exception("Unhandled error in /events/chat_reply")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@router.post("/debug/context", response_model=DebugContextResponse)
def debug_context(
    payload: ChatEvent,
    db: Session = Depends(get_db),
) -> DebugContextResponse:
    context = service.build_chat_context(
        db,
        stream_id=payload.stream_id,
        username=payload.username,
        text=payload.text,
    )
    return DebugContextResponse(**context)

@router.get("/debug/prompts/{name}")
def get_prompt(name: str) -> dict:
    from app.prompt_store import PromptStore
    store = PromptStore()
    return {"name": name, "content": store.read(name)}

@router.post("/events/dynamic_prompt", response_model=DynamicPromptResponse)
async def dynamic_prompt_event(payload: DynamicPromptRequest) -> DynamicPromptResponse:
    result, message = await dynamic_prompt_service.generate(
        prompt_name=payload.prompt,
        user=payload.user,
        data=payload.data,
    )
    return DynamicPromptResponse(result=result, message=message)

