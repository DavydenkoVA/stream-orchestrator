from __future__ import annotations
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.schemas.admin_llm_config import AdminLLMConfig
from app.services.llm_registry import LLMRegistry
from app.services.style_registry import StyleRegistry


@dataclass(slots=True)
class AdminValidationResult:
    valid: bool
    errors: list[str]
    config: AdminLLMConfig | None = None
    raw: dict | None = None


class LLMConfigAdminService:
    PROVIDER_PATTERN = re.compile(r"^providers\[(\d+)\]\[(name|provider)\]$")
    MODEL_PATTERN = re.compile(r"^providers\[(\d+)\]\[models\]\[(\d+)\]\[(name|api_key|base_url|model)\]$")
    FEATURE_PATTERN = re.compile(r"^feature_settings\[(\d+)\]\[(name|provider|temperature|max_output_tokens|style)\]$")

    def __init__(self, registry: LLMRegistry, style_registry: StyleRegistry | None = None) -> None:
        self.registry = registry
        self.style_registry = style_registry or StyleRegistry()

    def read_raw_config(self) -> dict:
        config_path = Path(self.registry.config_path)
        if not config_path.exists():
            return {}
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    def read_styles_raw(self, styles_path: str | Path) -> dict:
        path = Path(styles_path)
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def parse_form_data(self, form: dict[str, str]) -> dict:
        providers: dict[int, dict] = {}
        features: dict[int, dict] = {}

        for key, value in form.items():
            m_provider = self.PROVIDER_PATTERN.match(key)
            if m_provider:
                provider_idx = int(m_provider.group(1))
                field = m_provider.group(2)
                providers.setdefault(provider_idx, {"models": {}})[field] = str(value).strip()
                continue

            m_model = self.MODEL_PATTERN.match(key)
            if m_model:
                provider_idx = int(m_model.group(1))
                model_idx = int(m_model.group(2))
                field = m_model.group(3)
                provider = providers.setdefault(provider_idx, {"models": {}})
                models = provider.setdefault("models", {})
                models.setdefault(model_idx, {})[field] = str(value).strip()
                continue

            m_feature = self.FEATURE_PATTERN.match(key)
            if m_feature:
                feature_idx = int(m_feature.group(1))
                field = m_feature.group(2)
                features.setdefault(feature_idx, {})[field] = str(value).strip()

        ordered_providers = []
        for provider_idx in sorted(providers.keys()):
            provider_item = providers[provider_idx]
            models_map = provider_item.get("models", {})
            models = [models_map[k] for k in sorted(models_map.keys())]
            ordered_providers.append(
                {
                    "name": provider_item.get("name", ""),
                    "provider": provider_item.get("provider", ""),
                    "models": models,
                }
            )

        ordered_features = [features[i] for i in sorted(features.keys())]
        return {
            "providers": ordered_providers,
            "feature_settings": ordered_features,
        }

    def validate_form_data(self, form: dict[str, str]) -> AdminValidationResult:
        raw = self.parse_form_data(form)

        try:
            config = AdminLLMConfig.model_validate(raw)
            normalized_raw = config.to_raw_dict()
            self.registry.validate_raw(normalized_raw)
            style_errors = self._validate_style_references(normalized_raw)
            if style_errors:
                return AdminValidationResult(valid=False, errors=style_errors)
            return AdminValidationResult(valid=True, errors=[], config=config, raw=normalized_raw)
        except ValidationError as exc:
            errors = [self._humanize_error(error) for error in exc.errors()]
            return AdminValidationResult(valid=False, errors=errors)
        except ValueError as exc:
            return AdminValidationResult(valid=False, errors=[str(exc)])

    def apply_form_data(self, form: dict[str, str]) -> AdminValidationResult:
        validation = self.validate_form_data(form)
        if not validation.valid or validation.raw is None:
            return validation

        config_path = Path(self.registry.config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_payload = yaml.safe_dump(
            validation.raw,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(config_path.parent),
            delete=False,
            prefix=f"{config_path.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_file.write(yaml_payload)
            temp_path = Path(temp_file.name)

        try:
            os.replace(temp_path, config_path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

        snapshot = self.registry.build_snapshot_from_raw(validation.raw)
        self.registry.apply_snapshot(snapshot)
        return validation

    def _validate_style_references(self, raw: dict) -> list[str]:
        errors: list[str] = []
        features = raw.get("feature_settings", {})
        for feature_name, feature_cfg in features.items():
            style_value = feature_cfg.get("style")
            style_error = self.style_registry.validate_style_reference(
                style_value if isinstance(style_value, str) else None
            )
            if style_error is not None:
                errors.append(f"feature '{feature_name}': {style_error}")
        return errors

    @staticmethod
    def _humanize_error(error: Mapping[str, Any]) -> str:
        loc = error.get("loc", ())
        message = str(error.get("msg", "validation error"))
        lowered = message.lower()

        if "providers list is empty" in lowered:
            return "providers list is empty"
        if "models list is empty" in lowered:
            return "models list is empty"
        if "duplicate provider name" in lowered:
            return "duplicate provider name"
        if "duplicate model name inside provider" in lowered:
            return message
        if "provider references unknown provider" in lowered:
            return "provider references unknown provider"
        if "unsupported provider type" in lowered:
            return message
        if "unknown feature name" in lowered:
            return message
        if "missing required feature setting" in lowered:
            return message
        if "duplicate feature name" in lowered:
            return "duplicate feature name"
        if "invalid temperature" in lowered:
            return "invalid temperature"
        if "invalid max_output_tokens" in lowered:
            return "invalid max_output_tokens"

        if any(part == "api_key" for part in loc) and "at least 1 character" in lowered:
            return "api_key is empty"
        if any(part == "name" for part in loc) and "at least 1 character" in lowered:
            return "name is empty"
        if any(part == "model" for part in loc) and "at least 1 character" in lowered:
            return "model is empty"

        return message
