from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api import routes as api_routes
from app.config import settings
from app.services.llm_config_admin_service import LLMConfigAdminService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")



def _build_view_model() -> dict:
    admin_service = LLMConfigAdminService(api_routes.service.llm_registry)
    raw_config = admin_service.read_raw_config()
    styles_raw = admin_service.read_styles_raw(settings.llm_styles_config_path)
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

    features_list = []
    for feature_name, feature_cfg in features.items():
        features_list.append(
            {
                "name": feature_name,
                "provider": feature_cfg.get("provider", ""),
                "temperature": feature_cfg.get("temperature", settings.llm_temperature),
                "max_output_tokens": feature_cfg.get(
                    "max_output_tokens", settings.llm_max_output_tokens
                ),
                "style": feature_cfg.get("style", "default"),
            }
        )

    styles_preview = yaml.safe_dump(styles_raw, sort_keys=False, allow_unicode=True)

    return {
        "providers": providers_list,
        "features": features_list,
        "styles_preview": styles_preview,
        "metadata": snapshot_meta,
        "active_config_path": str(Path(settings.llm_profiles_config_path)),
    }




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
def get_playground(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/playground_placeholder.html",
        context={"active_page": "playground", "page_title": "Playground"},
    )


@router.get("/traces", response_class=HTMLResponse)
def get_traces(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/traces_placeholder.html",
        context={"active_page": "traces", "page_title": "Traces"},
    )


@router.get("/admin/llm-config")
def get_llm_config_admin_legacy():
    return RedirectResponse(url="/llm-config", status_code=307)


@router.post("/llm-config/validate", response_class=HTMLResponse)
async def validate_llm_config(request: Request):
    return await _validate_llm_config_impl(request)


@router.post("/llm-config/apply", response_class=HTMLResponse)
async def apply_llm_config(request: Request):
    return await _apply_llm_config_impl(request)


@router.post("/admin/llm-config/validate", response_class=HTMLResponse)
async def validate_llm_config_legacy(request: Request):
    return await _validate_llm_config_impl(request)


@router.post("/admin/llm-config/apply", response_class=HTMLResponse)
async def apply_llm_config_legacy(request: Request):
    return await _apply_llm_config_impl(request)
