from __future__ import annotations
import dataclasses
import pathlib
import re
import types
import typing
import urllib
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session  # noqa: TC002

from app.api import routes as api_routes
from app.config import settings
from app.db import get_db
from app.observability.trace_context import get_trace_state
from app.observability.trace_helpers import (
    finish_trace_failure,
    finish_trace_success,
    start_trace,
    trace_failure,
    trace_success,
)
from app.observability.trace_status import (
    TRACE_RUN_ALLOWED_STATUSES,
    TRACE_STATUS_FILTER_ALL,
    TraceStatusValidationError,
    normalize_status_filter,
)
from app.services.llm_config_admin_service import LLMConfigAdminService
from app.services.llm_config_source import (
    SUPPORTED_FEATURE_NAMES,
    SUPPORTED_PROVIDER_TYPES,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    TEMPERATURE_STEP,
)
from app.services.styles_admin_service import StylesAdminService
from app.services.trace_read_service import TraceReadService


if TYPE_CHECKING:
    from app.services.style_registry import StyleRegistry


admin_router = APIRouter()
router = admin_router  # noqa: COP005
jinja_templates = Jinja2Templates(directory="app/templates")


_DYNAMIC_PROMPT_NAME_RE: typing.Final = re.compile(r"^[a-zA-Z0-9_-]+$")


_trace_read_service = TraceReadService()


@typing.final
class ResetStreamRequest(BaseModel):
    stream_id: str = Field(..., min_length=1, max_length=128)


@typing.final
class PromptSaveRequest(BaseModel):
    scope: str = Field(..., min_length=1, max_length=32)
    part: str = Field(..., min_length=1, max_length=64)
    content: str
    name: str | None = None


@typing.final
class DynamicPromptCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


@typing.final
class DossierRunRequest(BaseModel):
    stream_id: str = Field(..., min_length=1, max_length=128)
    username: str = Field(..., min_length=1, max_length=128)
    dossier_target: str = Field(..., min_length=1, max_length=128)


PROMPT_PARTS: typing.Final = types.MappingProxyType(
    {
        "chat": {
            "system_prompt": "chat_system.txt",
            "user_template": "chat_user_template.txt",
        },
        "dossier": {
            "system_prompt": "dossier_system.txt",
            "user_template": "dossier_user_template.txt",
        },
    }
)


def list_dynamic_prompt_names() -> list[str]:
    prompts_root: typing.Final = pathlib.Path(settings.prompts_dir) / "dynamic"
    if not prompts_root.exists():
        return []

    system_prompt_names: typing.Final[set[str]] = set()
    templates_set: typing.Final[set[str]] = set()

    for one_path in prompts_root.glob("*_system.txt"):
        system_prompt_names.add(one_path.name[: -len("_system.txt")])

    for one_path in prompts_root.glob("*_template.txt"):
        templates_set.add(one_path.name[: -len("_template.txt")])

    return sorted(system_prompt_names & templates_set)


def validate_dynamic_prompt_name(prompt_name: str) -> str:
    if prompt_name != prompt_name.strip():
        raise HTTPException(status_code=400, detail="Invalid dynamic prompt name")
    if not _DYNAMIC_PROMPT_NAME_RE.fullmatch(prompt_name):
        raise HTTPException(status_code=400, detail="Invalid dynamic prompt name")
    return prompt_name


def get_prompt_file_for(
    prompt_scope: str,
    prompt_part: str,
    *,
    prompt_name: str | None = None,
) -> str:
    if prompt_scope == "dynamic":
        if not prompt_name:
            raise HTTPException(status_code=400, detail="name is required for dynamic prompts")
        validated_prompt_name: typing.Final = validate_dynamic_prompt_name(prompt_name)
        if prompt_part == "system_prompt":
            return f"dynamic/{validated_prompt_name}_system.txt"
        if prompt_part == "template_prompt":
            return f"dynamic/{validated_prompt_name}_template.txt"
        raise HTTPException(status_code=400, detail="Invalid dynamic prompt part")
    if prompt_scope not in PROMPT_PARTS:
        raise HTTPException(status_code=400, detail="Invalid prompt scope")
    file_name: typing.Final = PROMPT_PARTS[prompt_scope].get(prompt_part)
    if not file_name:
        raise HTTPException(status_code=400, detail="Invalid prompt part")
    return file_name


def _get_trace_run_id() -> str | None:
    trace_state: typing.Final = get_trace_state()
    if trace_state is None:
        return None
    return trace_state.trace_id


def build_view_model() -> dict[str, typing.Any]:
    style_registry: typing.Final = api_routes.service.style_registry
    raw_config: typing.Final = _read_admin_raw_config(style_registry)

    selector_options: typing.Final = [
        dataclasses.asdict(one_option) for one_option in style_registry.selector_options()
    ]
    snapshot_meta: typing.Final = api_routes.service.llm_registry.get_snapshot_metadata()

    providers: typing.Final = raw_config.get("providers", {})
    features: typing.Final = raw_config.get("feature_settings", {})

    providers_list: typing.Final = []
    for provider_name, provider_cfg in providers.items():
        providers_list.append(
            {
                "name": provider_name,
                "provider": provider_cfg.get("provider", ""),
                "models": provider_cfg.get("models", []) or [],
            }
        )

    feature_defaults: typing.Final = {
        feature_name: {
            "provider": "",
            "temperature": settings.llm_temperature,
            "max_output_tokens": settings.llm_max_output_tokens,
            "style": "",
        }
        for feature_name in SUPPORTED_FEATURE_NAMES
    }

    features_list: typing.Final = []
    for feature_name in SUPPORTED_FEATURE_NAMES:
        feature_config = {**feature_defaults[feature_name], **(features.get(feature_name) or {})}
        style_value = str(feature_config.get("style", "") or "").strip()
        features_list.append(
            {
                "name": feature_name,
                "provider": feature_config.get("provider", ""),
                "temperature": feature_config.get("temperature", settings.llm_temperature),
                "max_output_tokens": feature_config.get("max_output_tokens", settings.llm_max_output_tokens),
                "style": style_value,
                "style_options": _resolve_selector_options_with_legacy(
                    style_registry,
                    style_value,
                ),
            }
        )

    return {
        "providers": providers_list,
        "provider_options": _extract_top_level_provider_names(raw_config),
        "features": features_list,
        "provider_type_options": list(SUPPORTED_PROVIDER_TYPES),
        "temperature_min": TEMPERATURE_MIN,
        "temperature_max": TEMPERATURE_MAX,
        "temperature_step": TEMPERATURE_STEP,
        "style_options": selector_options,
        "metadata": snapshot_meta,
        "active_config_path": str(pathlib.Path(settings.llm_profiles_config_path)),
    }


def _read_admin_raw_config(style_registry: StyleRegistry) -> dict[str, typing.Any]:
    admin_service: typing.Final = LLMConfigAdminService(
        api_routes.service.llm_registry,
        style_registry=style_registry,
    )
    raw_config: typing.Final = admin_service.read_raw_config()
    if raw_config:
        return raw_config
    return api_routes.service.llm_registry.export_raw_config()


def _extract_top_level_provider_names(raw_config: dict[str, typing.Any]) -> list[str]:
    providers: typing.Final = raw_config.get("providers", {})
    if not isinstance(providers, dict):
        return []

    provider_names: typing.Final[list[str]] = []
    for one_provider_name in providers:
        normalized_provider_name = str(one_provider_name).strip()
        if normalized_provider_name and normalized_provider_name not in provider_names:
            provider_names.append(normalized_provider_name)
    return provider_names


def _resolve_selector_options_with_legacy(
    style_registry: StyleRegistry,
    current_value: str | None,
) -> list[dict[str, str]]:
    options: typing.Final = [dataclasses.asdict(one_option) for one_option in style_registry.selector_options()]
    normalized_current: typing.Final = (current_value or "").strip().lower()
    known_values: typing.Final = {one_item["value"] for one_item in options}
    if normalized_current and normalized_current not in known_values:
        options.append(
            {
                "value": normalized_current,
                "label": f"[missing: {normalized_current}]",
                "kind": "missing",
            }
        )
    return options


def enforce_config_mutation_access() -> None:
    """Restrict config mutation routes to non-production-style environments."""
    allowed_envs: typing.Final = {"local", "dev", "test"}
    current_env: typing.Final = settings.app_env.lower().strip()
    if current_env not in allowed_envs:
        raise HTTPException(
            status_code=403,
            detail=("LLM config mutation routes are disabled outside local/dev/test environments."),
        )


async def _read_form_data(http_request: Request) -> dict[str, str]:
    request_body: typing.Final = (await http_request.body()).decode("utf-8")
    return dict(urllib.parse.parse_qsl(request_body, keep_blank_values=True))


async def _validate_llm_config_impl(http_request: Request) -> HTMLResponse:
    form_data: typing.Final = await _read_form_data(http_request)

    admin_service: typing.Final = LLMConfigAdminService(api_routes.service.llm_registry)
    result: typing.Final = admin_service.validate_form_data(form_data)

    return jinja_templates.TemplateResponse(
        request=http_request,
        name="admin/_status_panel.html",
        context={"result": result, "applied": False},
    )


async def _apply_llm_config_impl(http_request: Request) -> HTMLResponse:
    enforce_config_mutation_access()
    form_data: typing.Final = await _read_form_data(http_request)

    admin_service: typing.Final = LLMConfigAdminService(api_routes.service.llm_registry)
    result: typing.Final = admin_service.apply_form_data(form_data)

    return jinja_templates.TemplateResponse(
        request=http_request,
        name="admin/_status_panel.html",
        context={"result": result, "applied": True},
    )


@router.get("/", response_class=HTMLResponse)
def get_console_root(http_request: Request) -> HTMLResponse:
    view_model_data: typing.Final = build_view_model()
    return jinja_templates.TemplateResponse(
        request=http_request,
        name="admin/llm_config.html",
        context={**view_model_data, "active_page": "llm-config", "page_title": "LLM Config"},
    )


@router.get("/llm-config", response_class=HTMLResponse)
def get_llm_config(http_request: Request) -> HTMLResponse:
    view_model_data: typing.Final = build_view_model()
    return jinja_templates.TemplateResponse(
        request=http_request,
        name="admin/llm_config.html",
        context={**view_model_data, "active_page": "llm-config", "page_title": "LLM Config"},
    )


@router.get("/playground", response_class=HTMLResponse)
def get_playground(http_request: Request, mode: typing.Annotated[str, Query()] = "chat") -> HTMLResponse:
    normalized_mode: typing.Final = mode if mode in {"chat", "dynamic", "dossier"} else "chat"
    style_registry: typing.Final = api_routes.service.style_registry
    raw_config: typing.Final = _read_admin_raw_config(style_registry)
    return jinja_templates.TemplateResponse(
        request=http_request,
        name="admin/playground.html",
        context={
            "active_page": "playground",
            "page_title": "Playground",
            "mode": normalized_mode,
            "provider_options": _extract_top_level_provider_names(raw_config),
            "dynamic_style_options": [
                dataclasses.asdict(one_option) for one_option in style_registry.selector_options()
            ],
            "temperature_min": TEMPERATURE_MIN,
            "temperature_max": TEMPERATURE_MAX,
            "temperature_step": TEMPERATURE_STEP,
        },
    )


@router.get("/styles", response_class=HTMLResponse)
def get_styles(http_request: Request) -> HTMLResponse:
    style_registry: typing.Final = api_routes.service.style_registry
    styles_service: typing.Final = StylesAdminService(style_registry)
    styles_collection: typing.Final = styles_service.initial_styles()
    return jinja_templates.TemplateResponse(
        request=http_request,
        name="admin/styles.html",
        context={
            "active_page": "styles",
            "page_title": "Styles",
            "styles": [dataclasses.asdict(one_style) for one_style in styles_collection],
        },
    )


async def _validate_styles_impl(http_request: Request) -> HTMLResponse:
    form_data: typing.Final = await _read_form_data(http_request)
    styles_service: typing.Final = StylesAdminService(api_routes.service.style_registry)
    result: typing.Final = styles_service.validate_form_data(form_data)
    return jinja_templates.TemplateResponse(
        request=http_request,
        name="admin/_status_panel.html",
        context={"result": result, "applied": False},
    )


async def _apply_styles_impl(http_request: Request) -> HTMLResponse:
    enforce_config_mutation_access()
    form_data: typing.Final = await _read_form_data(http_request)
    styles_service: typing.Final = StylesAdminService(api_routes.service.style_registry)
    result: typing.Final = styles_service.apply_form_data(form_data)
    return jinja_templates.TemplateResponse(
        request=http_request,
        name="admin/_status_panel.html",
        context={"result": result, "applied": True},
    )


@router.get("/playground/api/dynamic-prompts")
def get_dynamic_prompt_names() -> dict[str, typing.Any]:
    prompt_names: typing.Final = list_dynamic_prompt_names()
    return {"items": [{"name": one_prompt_name} for one_prompt_name in prompt_names]}


@router.get("/playground/api/dynamic-prompts/{name}")
def get_dynamic_prompt_metadata(name: str) -> dict[str, typing.Any]:
    validated_name: typing.Final = validate_dynamic_prompt_name(name)
    if validated_name not in list_dynamic_prompt_names():
        raise HTTPException(status_code=404, detail="Dynamic prompt not found")

    system_name: typing.Final = f"dynamic/{validated_name}_system.txt"
    template_name: typing.Final = f"dynamic/{validated_name}_template.txt"

    store: typing.Final = api_routes.service.prompts

    try:
        required_fields: typing.Final = sorted(store.get_required_fields(template_name))
        required_data_fields: typing.Final = [one_field for one_field in required_fields if one_field != "user"]
        data_skeleton: typing.Final = dict.fromkeys(required_data_fields, "")
        system_prompt: typing.Final = store.read_raw(system_name)
        template_prompt: typing.Final = store.read_raw(template_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dynamic prompt not found") from exc

    return {
        "name": validated_name,
        "required_fields": required_fields,
        "required_data_fields": required_data_fields,
        "data_skeleton": data_skeleton,
        "system_prompt": system_prompt,
        "template_prompt": template_prompt,
    }


@router.post("/playground/api/dynamic-prompts/create")
def create_dynamic_prompt(payload: DynamicPromptCreateRequest) -> dict[str, typing.Any]:
    validated_name: typing.Final = validate_dynamic_prompt_name(payload.name)
    existing: typing.Final = set(list_dynamic_prompt_names())
    if validated_name in existing:
        raise HTTPException(status_code=400, detail="Dynamic prompt already exists")

    dynamic_root: typing.Final = pathlib.Path(settings.prompts_dir) / "dynamic"
    dynamic_root.mkdir(parents=True, exist_ok=True)
    system_path: typing.Final = dynamic_root / f"{validated_name}_system.txt"
    template_path: typing.Final = dynamic_root / f"{validated_name}_template.txt"
    system_path.write_text("", encoding="utf-8")
    template_path.write_text("", encoding="utf-8")
    return {"name": validated_name, "created": True}


@router.get("/playground/api/prompts/{scope}")
def get_prompt_sources(scope: str, name: typing.Annotated[str | None, Query()] = None) -> dict[str, typing.Any]:
    store: typing.Final = api_routes.service.prompts
    if scope == "dynamic":
        validated_name: typing.Final = validate_dynamic_prompt_name(name or "")
        return {
            "scope": scope,
            "name": validated_name,
            "items": [
                {
                    "part": "system_prompt",
                    "file": f"dynamic/{validated_name}_system.txt",
                    "content": store.read_raw(f"dynamic/{validated_name}_system.txt"),
                },
                {
                    "part": "template_prompt",
                    "file": f"dynamic/{validated_name}_template.txt",
                    "content": store.read_raw(f"dynamic/{validated_name}_template.txt"),
                },
            ],
        }
    part_map: typing.Final = PROMPT_PARTS.get(scope)
    if not part_map:
        raise HTTPException(status_code=400, detail="Invalid prompt scope")
    items: typing.Final = []
    for part, file_name in part_map.items():
        items.append({"part": part, "file": file_name, "content": store.read_raw(file_name)})
    return {"scope": scope, "items": items}


@router.post("/playground/api/prompts/save")
def save_prompt_source(payload: PromptSaveRequest) -> dict[str, typing.Any]:
    file_name: typing.Final = get_prompt_file_for(
        prompt_scope=payload.scope,
        prompt_part=payload.part,
        prompt_name=payload.name,
    )
    store: typing.Final = api_routes.service.prompts
    store.write(file_name, payload.content)
    return {"saved": True, "scope": payload.scope, "part": payload.part, "name": payload.name}


@router.post("/playground/api/dossier/run")
async def run_dossier_from_playground(
    payload: DossierRunRequest,
    http_request: Request,
    response: Response,
    database_session: typing.Annotated[Session, Depends(get_db)],
) -> dict[str, typing.Any]:
    start_trace(route=str(http_request.url.path), stream_id=payload.stream_id, db=database_session)
    try:
        reply_text, selected_route = await api_routes.service.run_dossier(
            database_session,
            stream_id=payload.stream_id,
            username=payload.username,
            target_username=payload.dossier_target,
        )
        trace_success("request.finish", "dossier playground request finished", payload={"route_result": selected_route})
        trace_run_id: typing.Final = _get_trace_run_id()
        if trace_run_id:
            response.headers["X-Trace-Id"] = trace_run_id
        finish_trace_success(summary=f"dossier {selected_route}")
        return {"reply_text": reply_text, "route": selected_route, "should_reply": bool(reply_text)}
    except Exception as exception_obj:
        error_code = "internal_error"
        if isinstance(exception_obj, HTTPException) and exception_obj.status_code in {400, 422}:
            error_code = "bad_request"
        trace_failure("request.finish", "dossier playground request failed", error_code=error_code)
        finish_trace_failure(error_code=error_code, summary="dossier playground failed")
        raise


@router.post("/playground/api/chat/reset-stream")
def reset_chat_stream(
    payload: ResetStreamRequest, database_session: typing.Annotated[Session, Depends(get_db)]
) -> dict[str, typing.Any]:
    stream_id: typing.Final = payload.stream_id.strip()
    if not stream_id:
        raise HTTPException(status_code=422, detail="stream_id must not be empty")

    deleted_count: typing.Final = api_routes.service.chat_memory.delete_stream_messages(
        database_session,
        stream_id=stream_id,
    )
    database_session.commit()

    return {
        "stream_id": stream_id,
        "deleted": True,
        "deleted_count": deleted_count,
    }


@router.get("/traces", response_class=HTMLResponse)
def get_traces(http_request: Request, run_id: typing.Annotated[str | None, Query()] = None) -> HTMLResponse:
    return jinja_templates.TemplateResponse(
        request=http_request,
        name="admin/traces.html",
        context={
            "active_page": "traces",
            "page_title": "Traces",
            "selected_run_id": run_id or "",
            "trace_status_filter_all": TRACE_STATUS_FILTER_ALL,
            "trace_status_options": TRACE_RUN_ALLOWED_STATUSES,
        },
    )


@router.get("/traces/api/runs")
def get_trace_runs(
    database_session: typing.Annotated[Session, Depends(get_db)],
    limit: typing.Annotated[int, Query(ge=1, le=200)] = 50,
    stream_id: typing.Annotated[str | None, Query()] = None,
    status: typing.Annotated[str | None, Query()] = None,
) -> dict[str, typing.Any]:
    try:
        normalized_status: typing.Final = normalize_status_filter(status)
    except TraceStatusValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc),
                "allowed_statuses": list(TRACE_RUN_ALLOWED_STATUSES),
            },
        ) from exc

    trace_items: typing.Final = _trace_read_service.list_runs(
        database_session,
        limit=limit,
        stream_id=stream_id,
        status=normalized_status,
    )
    return {"items": trace_items}


@router.get("/traces/api/runs/{run_id}")
def get_trace_run_detail(
    run_id: str,
    database_session: typing.Annotated[Session, Depends(get_db)],
) -> dict[str, typing.Any]:
    trace_run_detail: typing.Final = _trace_read_service.get_run_detail(database_session, run_id=run_id)
    if trace_run_detail is None:
        raise HTTPException(status_code=404, detail="Trace run not found")
    return trace_run_detail


@router.get("/admin/llm-config")
def get_llm_config_admin_legacy() -> RedirectResponse:
    return RedirectResponse(url="/llm-config", status_code=307)


@router.post("/llm-config/validate", response_class=HTMLResponse)
async def validate_llm_config(http_request: Request) -> HTMLResponse:
    return await _validate_llm_config_impl(http_request)


@router.post("/llm-config/apply", response_class=HTMLResponse)
async def apply_llm_config(http_request: Request) -> HTMLResponse:
    return await _apply_llm_config_impl(http_request)


@router.post("/styles/validate", response_class=HTMLResponse)
async def validate_styles(http_request: Request) -> HTMLResponse:
    return await _validate_styles_impl(http_request)


@router.post("/styles/apply", response_class=HTMLResponse)
async def apply_styles(http_request: Request) -> HTMLResponse:
    return await _apply_styles_impl(http_request)


@router.post("/admin/llm-config/validate", response_class=HTMLResponse)
async def validate_llm_config_legacy(http_request: Request) -> HTMLResponse:
    return await _validate_llm_config_impl(http_request)


@router.post("/admin/llm-config/apply", response_class=HTMLResponse)
async def apply_llm_config_legacy(http_request: Request) -> HTMLResponse:
    return await _apply_llm_config_impl(http_request)
