from __future__ import annotations

from html import escape
import json
from pathlib import Path
from urllib.parse import parse_qsl

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.api import routes as api_routes
from app.config import settings
from app.services.llm_config_admin_service import LLMConfigAdminService

router = APIRouter()


def _ensure_admin_ui_enabled() -> None:
    if settings.app_env == "dev" or settings.enable_admin_ui:
        return
    raise HTTPException(status_code=404, detail="Admin UI disabled")


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




async def _read_form_data(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {k: v for k, v in parse_qsl(body, keep_blank_values=True)}

def _render_status(valid: bool, errors: list[str], applied: bool) -> str:
    if valid:
        msg = (
            "<strong>Apply success.</strong> New config was validated, saved and activated."
            if applied
            else "<strong>Validation success.</strong> Config is valid and can be applied."
        )
        return f'<div class="card ok">{msg}</div>'

    items = "".join(f"<li>{escape(err)}</li>" for err in errors)
    header = "Apply failed" if applied else "Validation failed"
    return f'<div class="card danger"><strong>{header}.</strong><ul>{items}</ul></div>'


def _render_page(view: dict) -> str:
    metadata = view["metadata"]
    providers_json = json.dumps(view["providers"], ensure_ascii=False)
    features_json = json.dumps(view["features"], ensure_ascii=False)
    return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>LLM Config Admin</title>
<script src=\"https://unpkg.com/htmx.org@1.9.12\"></script>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; }}
.card {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px; margin-bottom: 12px; }}
.row {{ display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 8px; margin-bottom: 8px; }}
label {{ font-size: 12px; color: #444; display: block; }}
input {{ width: 100%; padding: 4px 6px; }}
.actions {{ display: flex; gap: 8px; margin: 16px 0; }}
.danger {{ background: #fff0f0; border: 1px solid #cc0000; color: #a60000; }}
.ok {{ background: #f0fff2; border: 1px solid #00a636; color: #06661f; }}
.muted {{ color: #666; font-size: 12px; }}
</style></head><body>
<h1>LLM Config Admin</h1>
<div class=\"card\">
<h3>Active snapshot metadata</h3>
<div>Config path: <code>{escape(str(metadata['config_path']))}</code></div>
<div>Loaded at: <code>{escape(str(metadata['loaded_at']))}</code></div>
<div>Last reload success: <strong>{escape(str(metadata['reload_success']))}</strong></div>
<div>Last reload error: <code>{escape(str(metadata['reload_error'] or '-'))}</code></div>
<div class=\"muted\">Summary: providers={metadata['providers_count']}, models={metadata['models_count']}, feature_settings={metadata['feature_settings_count']}</div>
</div>
<form id=\"llm-config-form\">
<h2>Providers</h2><div id=\"providers-container\"></div>
<button type=\"button\" onclick=\"addProvider()\">+ Add provider</button>
<h2 style=\"margin-top:20px;\">Feature settings</h2><div id=\"features-container\"></div>
<button type=\"button\" onclick=\"addFeature()\">+ Add feature</button>
<div class=\"actions\">
<button type=\"button\" hx-post=\"/admin/llm-config/validate\" hx-include=\"#llm-config-form\" hx-target=\"#status-panel\" hx-swap=\"innerHTML\">Validate</button>
<button type=\"button\" hx-post=\"/admin/llm-config/apply\" hx-include=\"#llm-config-form\" hx-target=\"#status-panel\" hx-swap=\"innerHTML\">Apply</button>
</div></form>
<div id=\"status-panel\"></div>
<div class=\"card\"><h3>Styles config (read-only preview)</h3><pre>{escape(view['styles_preview'])}</pre></div>
<template id=\"provider-template\"><div class=\"card provider-item\" data-provider-index=\"__P_INDEX__\"><div class=\"row\"><div><label>Provider name<input name=\"providers[__P_INDEX__][name]\" value=\"__P_NAME__\"></label></div><div><label>Provider type<input name=\"providers[__P_INDEX__][provider]\" value=\"__P_TYPE__\"></label></div></div><div class=\"models-container\"></div><button type=\"button\" class=\"remove-provider\">Remove provider</button><button type=\"button\" class=\"add-model\">+ Add model</button></div></template>
<template id=\"model-template\"><div class=\"card model-item\" data-model-index=\"__M_INDEX__\"><div class=\"row\"><div><label>Name<input name=\"providers[__P_INDEX__][models][__M_INDEX__][name]\" value=\"__M_NAME__\"></label></div><div><label>API key<input name=\"providers[__P_INDEX__][models][__M_INDEX__][api_key]\" value=\"__M_API__\"></label></div><div><label>Base URL<input name=\"providers[__P_INDEX__][models][__M_INDEX__][base_url]\" value=\"__M_BASE__\"></label></div><div><label>Model<input name=\"providers[__P_INDEX__][models][__M_INDEX__][model]\" value=\"__M_MODEL__\"></label></div></div><button type=\"button\" class=\"remove-model\">Remove model</button></div></template>
<template id=\"feature-template\"><div class=\"card feature-item\" data-feature-index=\"__F_INDEX__\"><div class=\"row\"><div><label>Feature name<input name=\"feature_settings[__F_INDEX__][name]\" value=\"__F_NAME__\"></label></div><div><label>Provider<input name=\"feature_settings[__F_INDEX__][provider]\" value=\"__F_PROVIDER__\"></label></div><div><label>Temperature<input name=\"feature_settings[__F_INDEX__][temperature]\" value=\"__F_TEMP__\"></label></div><div><label>Max output tokens<input name=\"feature_settings[__F_INDEX__][max_output_tokens]\" value=\"__F_TOKENS__\"></label></div></div><div class=\"row\"><div><label>Style<input name=\"feature_settings[__F_INDEX__][style]\" value=\"__F_STYLE__\"></label></div></div><button type=\"button\" class=\"remove-feature\">Remove feature</button></div></template>
<script>
let providerIndex=0;let featureIndex=0;
function htmlFromTemplate(id,r){{let h=document.getElementById(id).innerHTML;for(const [k,v] of Object.entries(r)){{h=h.replaceAll(k,v??'');}}return h;}}
function addProvider(provider={{name:'',provider:'',models:[]}}){{const i=providerIndex++;const c=document.getElementById('providers-container');const w=document.createElement('div');w.innerHTML=htmlFromTemplate('provider-template',{{'__P_INDEX__':String(i),'__P_NAME__':provider.name,'__P_TYPE__':provider.provider}});const n=w.firstElementChild;c.appendChild(n);const mc=n.querySelector('.models-container');const b=n.querySelector('.add-model');let mi=0;function addModel(model={{name:'',api_key:'',base_url:'',model:''}}){{const m=mi++;const mw=document.createElement('div');mw.innerHTML=htmlFromTemplate('model-template',{{'__P_INDEX__':String(i),'__M_INDEX__':String(m),'__M_NAME__':model.name,'__M_API__':model.api_key,'__M_BASE__':model.base_url,'__M_MODEL__':model.model}});const mn=mw.firstElementChild;mn.querySelector('.remove-model').addEventListener('click',()=>mn.remove());mc.appendChild(mn);}}b.addEventListener('click',()=>addModel());n.querySelector('.remove-provider').addEventListener('click',()=>n.remove());if(provider.models&&provider.models.length){{provider.models.forEach(addModel);}}else{{addModel();}}}}
function addFeature(feature={{name:'',provider:'',temperature:'0.7',max_output_tokens:'200',style:'default'}}){{const i=featureIndex++;const c=document.getElementById('features-container');const w=document.createElement('div');w.innerHTML=htmlFromTemplate('feature-template',{{'__F_INDEX__':String(i),'__F_NAME__':feature.name,'__F_PROVIDER__':feature.provider,'__F_TEMP__':String(feature.temperature??''),'__F_TOKENS__':String(feature.max_output_tokens??''),'__F_STYLE__':feature.style}});const n=w.firstElementChild;n.querySelector('.remove-feature').addEventListener('click',()=>n.remove());c.appendChild(n);}}
const initialProviders={providers_json};const initialFeatures={features_json};if(initialProviders.length===0){{addProvider();}}else{{initialProviders.forEach(addProvider);}}initialFeatures.forEach(addFeature);
</script></body></html>"""


@router.get("/admin/llm-config", response_class=HTMLResponse)
def get_llm_config_admin(request: Request):
    del request
    _ensure_admin_ui_enabled()
    return HTMLResponse(content=_render_page(_build_view_model()))


@router.post("/admin/llm-config/validate", response_class=HTMLResponse)
async def validate_llm_config(request: Request):
    _ensure_admin_ui_enabled()
    form_data = await _read_form_data(request)

    admin_service = LLMConfigAdminService(api_routes.service.llm_registry)
    result = admin_service.validate_form_data(form_data)

    return HTMLResponse(content=_render_status(result.valid, result.errors, applied=False))


@router.post("/admin/llm-config/apply", response_class=HTMLResponse)
async def apply_llm_config(request: Request):
    _ensure_admin_ui_enabled()
    form_data = await _read_form_data(request)

    admin_service = LLMConfigAdminService(api_routes.service.llm_registry)
    result = admin_service.apply_form_data(form_data)

    return HTMLResponse(content=_render_status(result.valid, result.errors, applied=True))
