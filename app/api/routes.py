import logging
import typing
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
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


api_router = APIRouter()
# Backward-compatible alias used by app.main and tests.
router = api_router  # noqa: COP005
router_service = RouterService()
# Backward-compatible alias used by tests/fixtures.
service = router_service  # noqa: COP005
dynamic_prompt_service = DynamicPromptService(
    llm_registry=service.llm_registry,
    llm_executor=service.llm_executor,
    prompts=service.prompts,
    style_prompt=service.style_prompt,
)
logger = logging.getLogger(__name__)  # noqa: COP005
HTTP_NOT_FOUND: typing.Final = 404
HTTP_BAD_REQUEST: typing.Final = 400
HTTP_UNPROCESSABLE_ENTITY: typing.Final = 422


def _run_trace_safely(action_name: str, operation: Callable[[], None]) -> None:
    try:
        operation()
    except Exception:  # noqa: BLE001
        logger.warning("trace operation failed: %s", action_name, exc_info=True)


def _start_request_trace(*, route_path: str, stream_id: str | None, database_session: Session) -> None:
    def run_trace_operation() -> None:
        start_trace(route=route_path, stream_id=stream_id, db=database_session)
        trace_info("request.start", "request started", payload={"route": route_path})

    _run_trace_safely("start_request_trace", run_trace_operation)


def resolve_error_code_for_exception(exception_obj: Exception) -> str:
    if isinstance(exception_obj, HTTPException):
        if exception_obj.status_code == HTTP_NOT_FOUND:
            return "not_found"
        if exception_obj.status_code in {HTTP_BAD_REQUEST, HTTP_UNPROCESSABLE_ENTITY}:
            return "bad_request"
    if isinstance(exception_obj, ValueError):
        return "validation_error"
    return "internal_error"


def set_trace_header(http_response: Response) -> None:
    trace_state: typing.Final = get_trace_state()
    if trace_state is None:
        return
    http_response.headers["X-Trace-Id"] = trace_state.trace_id


@api_router.get("/health")
def check_health() -> dict[str, typing.Any]:
    return {"ok": True}


@api_router.post("/events/chat_ingest")
def handle_ingest_chat_event(
    chat_event: ChatEvent,
    http_request: Request,
    database_session: typing.Annotated[Session, Depends(get_db)],
) -> IngestResponse:
    _start_request_trace(
        route_path=str(http_request.url.path),
        stream_id=chat_event.stream_id,
        database_session=database_session,
    )
    try:
        service.ingest_chat_event(
            database_session,
            stream_id=chat_event.stream_id,
            username=chat_event.username,
            text=chat_event.text,
            mentions_bot=chat_event.mentions_bot,
            role=chat_event.role,
            message_id=chat_event.message_id,
            reply_to_message_id=chat_event.reply_to_message_id,
            reply_to_username=chat_event.reply_to_username,
            reply_to_text=chat_event.reply_to_text,
        )
        _run_trace_safely(
            "chat_ingest_finish_success", lambda: trace_success("request.finish", "chat ingest request finished")
        )
        _run_trace_safely("chat_ingest_mark_success", lambda: finish_trace_success(summary="chat_ingest success"))
        return IngestResponse()
    except Exception as exception_obj:
        error_code: typing.Final = resolve_error_code_for_exception(exception_obj)
        _run_trace_safely(
            "chat_ingest_finish_failure",
            lambda: trace_failure("request.finish", "chat ingest request failed", error_code=error_code),
        )
        _run_trace_safely(
            "chat_ingest_mark_failure",
            lambda: finish_trace_failure(error_code=error_code, summary="chat_ingest failed"),
        )
        raise


@api_router.post("/events/chat_reply")
async def handle_reply_chat_event(
    chat_event: ChatEvent,
    http_request: Request,
    http_response: Response,
    database_session: typing.Annotated[Session, Depends(get_db)],
) -> ChatReply:
    _start_request_trace(
        route_path=str(http_request.url.path),
        stream_id=chat_event.stream_id,
        database_session=database_session,
    )
    try:
        reply_text, selected_route = await service.handle_chat_reply(
            database_session,
            stream_id=chat_event.stream_id,
            username=chat_event.username,
            text=chat_event.text,
            mentions_bot=chat_event.mentions_bot,
            role=chat_event.role,
            message_id=chat_event.message_id,
            reply_to_message_id=chat_event.reply_to_message_id,
            reply_to_username=chat_event.reply_to_username,
            reply_to_text=chat_event.reply_to_text,
        )

        _run_trace_safely(
            "chat_reply_finish_success",
            lambda: trace_success(
                "request.finish",
                "chat reply request finished",
                payload={"route_result": selected_route},
            ),
        )
        set_trace_header(http_response)
        _run_trace_safely(
            "chat_reply_mark_success",
            lambda: finish_trace_success(summary=f"chat_reply {selected_route}"),
        )
        return ChatReply(
            reply_text=reply_text,
            route=selected_route,
            should_reply=bool(reply_text),
        )
    except Exception as exception_obj:
        error_code: typing.Final = resolve_error_code_for_exception(exception_obj)
        _run_trace_safely(
            "chat_reply_finish_failure",
            lambda: trace_failure("request.finish", "chat reply request failed", error_code=error_code),
        )
        _run_trace_safely(
            "chat_reply_mark_failure",
            lambda: finish_trace_failure(error_code=error_code, summary="chat_reply failed"),
        )
        raise


@api_router.get("/debug/prompts/{name}")
def read_prompt(name: str) -> dict[str, typing.Any]:  # noqa: COP006
    return {"name": name, "content": PromptStore().read(name)}


@api_router.get("/debug/context")
def render_debug_context(
    stream_id: str,
    username: str,
    text_content: typing.Annotated[str, Query(alias="text")],
    database_session: typing.Annotated[Session, Depends(get_db)],
) -> DebugContextResponse:
    normalized_username: typing.Final = service.normalize_username(username)

    global_recent: typing.Final = service.chat_memory.recent_messages(
        database_session,
        stream_id=stream_id,
    )
    user_recent: typing.Final = service.chat_memory.recent_user_messages(
        database_session,
        stream_id=stream_id,
        username=normalized_username,
    )
    dialog_recent: typing.Final = service.chat_memory.recent_dialog_messages(
        database_session,
        stream_id=stream_id,
        username=normalized_username,
    )

    global_recent_block: typing.Final = [
        f"{one_message.username} [{one_message.role}]: {one_message.text}" for one_message in global_recent
    ]
    user_recent_block: typing.Final = [
        f"{one_message.username} [{one_message.role}]: {one_message.text}" for one_message in user_recent
    ]
    dialog_recent_block: typing.Final = [
        f"{one_message.username} [{one_message.role}]: {one_message.text}" for one_message in dialog_recent
    ]

    system_prompt: typing.Final = service.prompts.read("chat_system.txt")
    user_prompt: typing.Final = service.prompts.render(
        "chat_user_template.txt",
        username=username,
        text=text_content,
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


@api_router.post("/events/dynamic_prompt")
async def handle_dynamic_prompt_event(
    dynamic_prompt_request: DynamicPromptRequest,
    http_request: Request,
    http_response: Response,
    database_session: typing.Annotated[Session, Depends(get_db)],
) -> DynamicPromptResponse:
    _start_request_trace(route_path=str(http_request.url.path), stream_id=None, database_session=database_session)
    try:
        generation_result, generated_message = await dynamic_prompt_service.generate(
            db=database_session,
            prompt_name=dynamic_prompt_request.prompt,
            user=dynamic_prompt_request.user,
            data=dynamic_prompt_request.data,
            llm_provider_override=dynamic_prompt_request.llm.provider if dynamic_prompt_request.llm else None,
            style_override=dynamic_prompt_request.llm.style if dynamic_prompt_request.llm else None,
            temperature_override=dynamic_prompt_request.llm.temperature if dynamic_prompt_request.llm else None,
            max_output_tokens_override=dynamic_prompt_request.llm.max_output_tokens
            if dynamic_prompt_request.llm
            else None,
        )

        if generation_result != "success":
            generated_message = ""

        _run_trace_safely(
            "dynamic_prompt_finish_success",
            lambda: trace_success(
                "request.finish",
                "dynamic prompt request finished",
                payload={"result": generation_result},
            ),
        )
        set_trace_header(http_response)
        _run_trace_safely(
            "dynamic_prompt_mark_success",
            lambda: finish_trace_success(summary=f"dynamic_prompt {generation_result}"),
        )
        return DynamicPromptResponse(result=generation_result, message=generated_message)
    except Exception as exception_obj:
        error_code: typing.Final = resolve_error_code_for_exception(exception_obj)
        _run_trace_safely(
            "dynamic_prompt_finish_failure",
            lambda: trace_failure("request.finish", "dynamic prompt request failed", error_code=error_code),
        )
        _run_trace_safely(
            "dynamic_prompt_mark_failure",
            lambda: finish_trace_failure(error_code=error_code, summary="dynamic_prompt failed"),
        )
        raise
