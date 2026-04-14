from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.observability.trace_helpers import (
    finish_trace_failure,
    finish_trace_success,
    start_trace,
    trace_failure,
    trace_info,
    trace_success,
)
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

def _error_code_for_exception(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        if exc.status_code == 404:
            return "not_found"
        if exc.status_code in {400, 422}:
            return "bad_request"
    if isinstance(exc, ValueError):
        return "validation_error"
    return "internal_error"


@router.get("/health")
def healthcheck() -> dict:
    return {"ok": True}


@router.post("/events/chat_ingest", response_model=IngestResponse)
def ingest_chat_event(
    payload: ChatEvent,
    request: Request,
    db: Session = Depends(get_db),
) -> IngestResponse:
    start_trace(route=str(request.url.path), stream_id=payload.stream_id, db=db)
    trace_info("request.start", "chat ingest request started", payload={"route": str(request.url.path)})
    try:
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
        trace_success("request.finish", "chat ingest request finished")
        finish_trace_success(summary="chat_ingest success")
        return IngestResponse()
    except Exception as exc:
        error_code = _error_code_for_exception(exc)
        trace_failure("request.finish", "chat ingest request failed", error_code=error_code)
        finish_trace_failure(error_code=error_code, summary="chat_ingest failed")
        raise


@router.post("/events/chat_reply", response_model=ChatReply)
async def reply_chat_event(
    payload: ChatEvent,
    request: Request,
    db: Session = Depends(get_db),
) -> ChatReply:
    start_trace(route=str(request.url.path), stream_id=payload.stream_id, db=db)
    trace_info("request.start", "chat reply request started", payload={"route": str(request.url.path)})
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

        trace_success("request.finish", "chat reply request finished", payload={"route_result": route})
        finish_trace_success(summary=f"chat_reply {route}")
        return ChatReply(
            reply_text=reply_text,
            route=route,
            should_reply=bool(reply_text),
        )
    except Exception as exc:
        error_code = _error_code_for_exception(exc)
        trace_failure("request.finish", "chat reply request failed", error_code=error_code)
        finish_trace_failure(error_code=error_code, summary="chat_reply failed")
        raise


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
    request: Request,
    db: Session = Depends(get_db),
) -> DynamicPromptResponse:
    start_trace(route=str(request.url.path), stream_id=None, db=db)
    trace_info("request.start", "dynamic prompt request started", payload={"route": str(request.url.path)})
    try:
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

        trace_success("request.finish", "dynamic prompt request finished", payload={"result": result})
        finish_trace_success(summary=f"dynamic_prompt {result}")
        return DynamicPromptResponse(result=result, message=message)
    except Exception as exc:
        error_code = _error_code_for_exception(exc)
        trace_failure("request.finish", "dynamic prompt request failed", error_code=error_code)
        finish_trace_failure(error_code=error_code, summary="dynamic_prompt failed")
        raise
