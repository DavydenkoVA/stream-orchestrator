from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import re
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import routes as api_routes
from app.config import settings
from app.db import get_db
from app.observability.trace_status import (
    TRACE_RUN_ALLOWED_STATUSES,
    TRACE_STATUS_FILTER_ALL,
    TraceStatusValidationError,
    normalize_status_filter,
)
from app.services.llm_config_admin_service import LLMConfigAdminService
from app.services.styles_admin_service import StylesAdminService
from app.services.style_registry import StyleRegistry
from app.services.trace_read_service import TraceReadService
from app.services.llm_config_source import (
    SUPPORTED_FEATURE_NAMES,
    SUPPORTED_PROVIDER_TYPES,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    TEMPERATURE_STEP,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")




_DYNAMIC_PROMPT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


_trace_read_service = TraceReadService()


class ResetStreamRequest(BaseModel):
    stream_id: str = Field(..., min_length=1, max_length=128)


def _list_dynamic_prompt_names() -> list[str]:
    prompts_root = Path(settings.prompts_dir) / "dynamic"
    if not prompts_root.exists():
        return []

    systems: set[str] = set()
    templates_set: set[str] = set()

    for path in prompts_root.glob("*_system.txt"):
        systems.add(path.name[: -len("_system.txt")])

    for path in prompts_root.glob("*_template.txt"):
        templates_set.add(path.name[: -len("_template.txt")])

    return sorted(systems & templates_set)


def _validate_dynamic_prompt_name(name: str) -> str:
    if not _DYNAMIC_PROMPT_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail="Invalid dynamic prompt name")
    return name


def _build_view_model() -> dict:
    style_registry = api_routes.service.style_registry
    raw_config = _read_admin_raw_config(style_registry)

    selector_options = [asdict(option) for option in style_registry.selector_options()]
    snapshot_meta = api_routes.service.llm_registry.get_snapshot_metadata()

    providers = raw_config.get("providers", {})
    features = raw_config.get("feature_settings", {})

    providers_list = []
    for provider_name, provider_cfg in providers.items():
        providers_list.append(
            {
                "name": provider_name,
                "provider": provider_cfg.get("provider", ""),
                "models": provider_cfg.get("models", []) or [],
            }
        )

    feature_defaults = {
        feature_name: {
            "provider": "",
            "temperature": settings.llm_temperature,
            "max_output_tokens": settings.llm_max_output_tokens,
            "style": "",
        }
        for feature_name in SUPPORTED_FEATURE_NAMES
    }

    features_list = []
    for feature_name in SUPPORTED_FEATURE_NAMES:
        feature_cfg = {**feature_defaults[feature_name], **(features.get(feature_name) or {})}
        style_value = str(feature_cfg.get("style", "") or "").strip()
        features_list.append(
            {
                "name": feature_name,
                "provider": feature_cfg.get("provider", ""),
                "temperature": feature_cfg.get("temperature", settings.llm_temperature),
                "max_output_tokens": feature_cfg.get(
                    "max_output_tokens", settings.llm_max_output_tokens
                ),
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
        "active_config_path": str(Path(settings.llm_profiles_config_path)),
    }


def _read_admin_raw_config(style_registry: StyleRegistry) -> dict:
    admin_service = LLMConfigAdminService(
        api_routes.service.llm_registry,
        style_registry=style_registry,
    )
    raw_config = admin_service.read_raw_config()
    if raw_config:
        return raw_config
    return api_routes.service.llm_registry.export_raw_config()


def _extract_top_level_provider_names(raw_config: dict) -> list[str]:
    providers = raw_config.get("providers", {})
    if not isinstance(providers, dict):
        return []

    names: list[str] = []
    for provider_name in providers.keys():
        normalized = str(provider_name).strip()
        if normalized and normalized not in names:
            names.append(normalized)
    return names


def _resolve_selector_options_with_legacy(
    style_registry: StyleRegistry,
    current_value: str | None,
) -> list[dict[str, str]]:
    options = [asdict(option) for option in style_registry.selector_options()]
    normalized_current = (current_value or "").strip().lower()
    known_values = {item["value"] for item in options}
    if normalized_current and normalized_current not in known_values:
        options.append(
            {
                "value": normalized_current,
                "label": f"[missing: {normalized_current}]",
                "kind": "missing",
            }
        )
    return options




def _enforce_config_mutation_access() -> None:
    """Restrict config mutation routes to non-production-style environments."""
    allowed_envs = {"local", "dev", "test"}
    current_env = settings.app_env.lower().strip()
    if current_env not in allowed_envs:
        raise HTTPException(
            status_code=403,
            detail=(
                "LLM config mutation routes are disabled outside local/dev/test "
                "environments."
            ),
        )

async def _read_form_data(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {k: v for k, v in parse_qsl(body, keep_blank_values=True)}


async def _validate_llm_config_impl(request: Request) -> HTMLResponse:
    form_data = await _read_form_data(request)

    admin_service = LLMConfigAdminService(api_routes.service.llm_registry)
    result = admin_service.validate_form_data(form_data)

    return templates.TemplateResponse(
        request=request,
        name="admin/_status_panel.html",
        context={"result": result, "applied": False},
    )


async def _apply_llm_config_impl(request: Request) -> HTMLResponse:
    _enforce_config_mutation_access()
    form_data = await _read_form_data(request)

    admin_service = LLMConfigAdminService(api_routes.service.llm_registry)
    result = admin_service.apply_form_data(form_data)

    return templates.TemplateResponse(
        request=request,
        name="admin/_status_panel.html",
        context={"result": result, "applied": True},
    )


@router.get("/", response_class=HTMLResponse)
def get_console_root(request: Request):
    view = _build_view_model()
    return templates.TemplateResponse(
        request=request,
        name="admin/llm_config.html",
        context={**view, "active_page": "llm-config", "page_title": "LLM Config"},
    )


@router.get("/llm-config", response_class=HTMLResponse)
def get_llm_config(request: Request):
    view = _build_view_model()
    return templates.TemplateResponse(
        request=request,
        name="admin/llm_config.html",
        context={**view, "active_page": "llm-config", "page_title": "LLM Config"},
    )


@router.get("/playground", response_class=HTMLResponse)
def get_playground(request: Request, mode: str = Query(default="chat")):
    normalized_mode = "dynamic" if mode == "dynamic" else "chat"
    style_registry = api_routes.service.style_registry
    raw_config = _read_admin_raw_config(style_registry)
    return templates.TemplateResponse(
        request=request,
        name="admin/playground.html",
        context={
            "active_page": "playground",
            "page_title": "Playground",
            "mode": normalized_mode,
            "provider_options": _extract_top_level_provider_names(raw_config),
            "dynamic_style_options": [asdict(option) for option in style_registry.selector_options()],
            "temperature_min": TEMPERATURE_MIN,
            "temperature_max": TEMPERATURE_MAX,
            "temperature_step": TEMPERATURE_STEP,
        },
    )


@router.get("/styles", response_class=HTMLResponse)
def get_styles(request: Request):
    style_registry = api_routes.service.style_registry
    styles_service = StylesAdminService(style_registry)
    styles = styles_service.initial_styles()
    return templates.TemplateResponse(
        request=request,
        name="admin/styles.html",
        context={
            "active_page": "styles",
            "page_title": "Styles",
            "styles": [asdict(style) for style in styles],
        },
    )


async def _validate_styles_impl(request: Request) -> HTMLResponse:
    form_data = await _read_form_data(request)
    styles_service = StylesAdminService(api_routes.service.style_registry)
    result = styles_service.validate_form_data(form_data)
    return templates.TemplateResponse(
        request=request,
        name="admin/_status_panel.html",
        context={"result": result, "applied": False},
    )


async def _apply_styles_impl(request: Request) -> HTMLResponse:
    _enforce_config_mutation_access()
    form_data = await _read_form_data(request)
    styles_service = StylesAdminService(api_routes.service.style_registry)
    result = styles_service.apply_form_data(form_data)
    return templates.TemplateResponse(
        request=request,
        name="admin/_status_panel.html",
        context={"result": result, "applied": True},
    )


@router.get("/playground/api/dynamic-prompts")
def get_dynamic_prompt_names() -> dict:
    names = _list_dynamic_prompt_names()
    return {"items": [{"name": name} for name in names]}


@router.get("/playground/api/dynamic-prompts/{name}")
def get_dynamic_prompt_metadata(name: str) -> dict:
    validated_name = _validate_dynamic_prompt_name(name)
    if validated_name not in _list_dynamic_prompt_names():
        raise HTTPException(status_code=404, detail="Dynamic prompt not found")

    system_name = f"dynamic/{validated_name}_system.txt"
    template_name = f"dynamic/{validated_name}_template.txt"

    store = api_routes.service.prompts

    try:
        required_fields = sorted(store.get_required_fields(template_name))
        required_data_fields = [field for field in required_fields if field != "user"]
        data_skeleton = {field: "" for field in required_data_fields}
        system_prompt = store.read(system_name)
        template_prompt = store.read(template_name)
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


@router.post("/playground/api/chat/reset-stream")
def reset_chat_stream(payload: ResetStreamRequest, db: Session = Depends(get_db)) -> dict:
    stream_id = payload.stream_id.strip()
    if not stream_id:
        raise HTTPException(status_code=422, detail="stream_id must not be empty")

    deleted_count = api_routes.service.chat_memory.delete_stream_messages(
        db,
        stream_id=stream_id,
    )
    db.commit()

    return {
        "stream_id": stream_id,
        "deleted": True,
        "deleted_count": deleted_count,
    }


@router.get("/traces", response_class=HTMLResponse)
def get_traces(request: Request, run_id: str | None = Query(default=None)):
    return templates.TemplateResponse(
        request=request,
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
    limit: int = Query(default=50, ge=1, le=200),
    stream_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        normalized_status = normalize_status_filter(status)
    except TraceStatusValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc),
                "allowed_statuses": list(TRACE_RUN_ALLOWED_STATUSES),
            },
        ) from exc

    items = _trace_read_service.list_runs(
        db,
        limit=limit,
        stream_id=stream_id,
        status=normalized_status,
    )
    return {"items": items}


@router.get("/traces/api/runs/{run_id}")
def get_trace_run_detail(run_id: str, db: Session = Depends(get_db)) -> dict:
    detail = _trace_read_service.get_run_detail(db, run_id=run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Trace run not found")
    return detail


@router.get("/admin/llm-config")
def get_llm_config_admin_legacy():
    return RedirectResponse(url="/llm-config", status_code=307)


@router.post("/llm-config/validate", response_class=HTMLResponse)
async def validate_llm_config(request: Request):
    return await _validate_llm_config_impl(request)


@router.post("/llm-config/apply", response_class=HTMLResponse)
async def apply_llm_config(request: Request):
    return await _apply_llm_config_impl(request)


@router.post("/styles/validate", response_class=HTMLResponse)
async def validate_styles(request: Request):
    return await _validate_styles_impl(request)


@router.post("/styles/apply", response_class=HTMLResponse)
async def apply_styles(request: Request):
    return await _apply_styles_impl(request)


@router.post("/admin/llm-config/validate", response_class=HTMLResponse)
async def validate_llm_config_legacy(request: Request):
    return await _validate_llm_config_impl(request)


@router.post("/admin/llm-config/apply", response_class=HTMLResponse)
async def apply_llm_config_legacy(request: Request):
    return await _apply_llm_config_impl(request)
