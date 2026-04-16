import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.observability.trace_context import get_trace_state
from app.observability.trace_helpers import (
    finish_trace_failure,
    finish_trace_success,
    start_trace,
    trace_failure,
    trace_info,
    trace_success,
)
from app.prompt_store import PromptStore
from app.schemas.dynamic_prompt import DynamicPromptRequest, DynamicPromptResponse
from app.schemas.events import ChatEvent
from app.schemas.responses import ChatReply, DebugContextResponse, IngestResponse
from app.services.dynamic_prompt_service import DynamicPromptService
from app.services.router import RouterService


router = APIRouter()
service = RouterService()
dynamic_prompt_service = DynamicPromptService(
    llm_registry=service.llm_registry,
    llm_executor=service.llm_executor,
    prompts=service.prompts,
    style_prompt=service.style_prompt,
)
logger = logging.getLogger(__name__)
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400
HTTP_UNPROCESSABLE_ENTITY = 422


def _run_trace_safely(action: str, operation: Callable[[], None]) -> None:
    try:
        operation()
    except Exception:  # noqa: BLE001
        logger.warning("trace operation failed: %s", action, exc_info=True)


def _start_request_trace(*, route: str, stream_id: str | None, db: Session) -> None:
    def _operation() -> None:
        start_trace(route=route, stream_id=stream_id, db=db)
        trace_info("request.start", "request started", payload={"route": route})

    _run_trace_safely("start_request_trace", _operation)


def _error_code_for_exception(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        if exc.status_code == HTTP_NOT_FOUND:
            return "not_found"
        if exc.status_code in {HTTP_BAD_REQUEST, HTTP_UNPROCESSABLE_ENTITY}:
            return "bad_request"
    if isinstance(exc, ValueError):
        return "validation_error"
    return "internal_error"


def _attach_trace_header(response: Response) -> None:
    state = get_trace_state()
    if state is None:
        return
    response.headers["X-Trace-Id"] = state.trace_id


@router.get("/health")
def healthcheck() -> dict[str, Any]:
    return {"ok": True}


@router.post("/events/chat_ingest")
def ingest_chat_event(
    payload: ChatEvent,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> IngestResponse:
    route = str(request.url.path)
    _start_request_trace(route=route, stream_id=payload.stream_id, db=db)
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
        _run_trace_safely(
            "chat_ingest_finish_success", lambda: trace_success("request.finish", "chat ingest request finished")
        )
        _run_trace_safely("chat_ingest_mark_success", lambda: finish_trace_success(summary="chat_ingest success"))
        return IngestResponse()
    except Exception as exc:
        error_code = _error_code_for_exception(exc)
        _run_trace_safely(
            "chat_ingest_finish_failure",
            lambda: trace_failure("request.finish", "chat ingest request failed", error_code=error_code),
        )
        _run_trace_safely(
            "chat_ingest_mark_failure",
            lambda: finish_trace_failure(error_code=error_code, summary="chat_ingest failed"),
        )
        raise


@router.post("/events/chat_reply")
async def reply_chat_event(
    payload: ChatEvent,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> ChatReply:
    route = str(request.url.path)
    _start_request_trace(route=route, stream_id=payload.stream_id, db=db)
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

        _run_trace_safely(
            "chat_reply_finish_success",
            lambda: trace_success("request.finish", "chat reply request finished", payload={"route_result": route}),
        )
        _attach_trace_header(response)
        _run_trace_safely("chat_reply_mark_success", lambda: finish_trace_success(summary=f"chat_reply {route}"))
        return ChatReply(
            reply_text=reply_text,
            route=route,
            should_reply=bool(reply_text),
        )
    except Exception as exc:
        error_code = _error_code_for_exception(exc)
        _run_trace_safely(
            "chat_reply_finish_failure",
            lambda: trace_failure("request.finish", "chat reply request failed", error_code=error_code),
        )
        _run_trace_safely(
            "chat_reply_mark_failure",
            lambda: finish_trace_failure(error_code=error_code, summary="chat_reply failed"),
        )
        raise


@router.get("/debug/prompts/{name}")
def get_prompt(name: str) -> dict[str, Any]:
    store = PromptStore()
    return {"name": name, "content": store.read(name)}


@router.get("/debug/context")
def debug_context(
    stream_id: str,
    username: str,
    text: str,
    db: Annotated[Session, Depends(get_db)],
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


@router.post("/events/dynamic_prompt")
async def dynamic_prompt_event(
    payload: DynamicPromptRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> DynamicPromptResponse:
    route = str(request.url.path)
    _start_request_trace(route=route, stream_id=None, db=db)
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

        _run_trace_safely(
            "dynamic_prompt_finish_success",
            lambda: trace_success("request.finish", "dynamic prompt request finished", payload={"result": result}),
        )
        _attach_trace_header(response)
        _run_trace_safely(
            "dynamic_prompt_mark_success",
            lambda: finish_trace_success(summary=f"dynamic_prompt {result}"),
        )
        return DynamicPromptResponse(result=result, message=message)
    except Exception as exc:
        error_code = _error_code_for_exception(exc)
        _run_trace_safely(
            "dynamic_prompt_finish_failure",
            lambda: trace_failure("request.finish", "dynamic prompt request failed", error_code=error_code),
        )
        _run_trace_safely(
            "dynamic_prompt_mark_failure",
            lambda: finish_trace_failure(error_code=error_code, summary="dynamic_prompt failed"),
        )
        raise
