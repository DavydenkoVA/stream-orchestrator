from __future__ import annotations
import typing
from dataclasses import dataclass  # noqa: COP002
from datetime import UTC, datetime  # noqa: COP002
from pathlib import Path
from typing import TYPE_CHECKING, Any  # noqa: COP002

import yaml

from app.config import settings
from app.integrations.llm.factory import build_llm_provider_from_config
from app.services.llm_config_source import SUPPORTED_FEATURE_NAMES


if TYPE_CHECKING:
    from app.integrations.llm.base import LLMProvider


@dataclass(slots=True)
class ModelEndpointConfig:  # noqa: COP012, COP014
    name: str  # noqa: COP004
    api_key: str  # noqa: COP004
    base_url: str
    model: str  # noqa: COP004


@dataclass(slots=True)
class ProviderPoolConfig:  # noqa: COP012, COP014
    name: str  # noqa: COP004
    provider: str
    models: list[ModelEndpointConfig]  # noqa: COP004


@dataclass(slots=True)
class FeatureLLMSettings:  # noqa: COP012, COP014
    feature_name: str
    provider_name: str
    temperature: float
    max_output_tokens: int
    style: str = "default"  # noqa: COP004


@dataclass(slots=True)
class LLMSnapshot:  # noqa: COP012, COP014
    providers: dict[str, ProviderPoolConfig]
    feature_settings: dict[str, FeatureLLMSettings]
    loaded_at: datetime


class LLMRegistry:  # noqa: COP012
    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = Path(config_path or settings.llm_profiles_config_path)
        self._provider_instances: dict[str, tuple[str, LLMProvider]] = {}
        self._snapshot: LLMSnapshot | None = None
        self._last_reload_success: bool = False
        self._last_reload_error: str | None = None
        self.reload_from_disk()

    def _build_snapshot(  # noqa: C901
        self,
        raw: dict[str, Any],  # noqa: COP006
        *,
        loaded_at: datetime | None = None,
    ) -> LLMSnapshot:
        providers_raw: typing.Final = raw.get("providers", {})
        feature_settings_raw: typing.Final = raw.get("feature_settings", {})

        if not providers_raw:
            raise ValueError("llm_profiles.yml: 'providers' section is empty")

        providers: typing.Final[dict[str, ProviderPoolConfig]] = {}
        feature_settings: typing.Final[dict[str, FeatureLLMSettings]] = {}

        for provider_name, cfg in providers_raw.items():
            model_items = cfg.get("models", []) or []
            if not model_items:
                raise ValueError(f"llm_profiles.yml: provider '{provider_name}' has empty models list")

            models: list[ModelEndpointConfig] = []  # noqa: COP005
            seen_model_names: set[str] = set()
            for item in model_items:  # noqa: COP015
                model_name = str(item.get("name", "")).strip()
                if not model_name:
                    raise ValueError(f"llm_profiles.yml: provider '{provider_name}' has model with empty name")
                if model_name in seen_model_names:
                    raise ValueError(
                        f"llm_profiles.yml: provider '{provider_name}' has duplicate model name '{model_name}'"
                    )
                seen_model_names.add(model_name)

                api_key = str(item.get("api_key", "")).strip()  # noqa: COP005
                if not api_key:
                    raise ValueError(f"llm_profiles.yml: provider '{provider_name}' has model with empty api_key")

                model_id = str(item.get("model", "")).strip()
                if not model_id:
                    raise ValueError(f"llm_profiles.yml: provider '{provider_name}' has model with empty model")

                models.append(
                    ModelEndpointConfig(
                        name=model_name,
                        api_key=api_key,
                        base_url=str(item.get("base_url", "")).strip(),
                        model=model_id,
                    )
                )

            provider_kind = str(cfg.get("provider", "")).strip()
            if not provider_kind:
                raise ValueError(f"llm_profiles.yml: provider '{provider_name}' has empty provider type")

            providers[provider_name] = ProviderPoolConfig(
                name=provider_name,
                provider=provider_kind,
                models=models,
            )

        for feature_name, cfg in feature_settings_raw.items():
            provider_name = str(cfg.get("provider", "")).strip()

            if provider_name not in providers:
                raise ValueError(
                    f"llm_profiles.yml: feature '{feature_name}' refers to unknown provider '{provider_name}'"
                )

            feature_settings[feature_name] = FeatureLLMSettings(
                feature_name=feature_name,
                provider_name=provider_name,
                temperature=float(cfg.get("temperature", settings.llm_temperature)),
                max_output_tokens=int(cfg.get("max_output_tokens", settings.llm_max_output_tokens)),
                style=str(cfg.get("style", "default")).strip() or "default",
            )

        if "chat" not in feature_settings:
            first_provider: typing.Final = next(iter(providers.keys()))
            feature_settings["chat"] = FeatureLLMSettings(
                feature_name="chat",
                provider_name=first_provider,
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
                style="default",
            )

        return LLMSnapshot(
            providers=providers,
            feature_settings=feature_settings,
            loaded_at=loaded_at or datetime.now(UTC),
        )

    def _read_raw_from_disk(self) -> dict[str, Any]:
        if not self.config_path.exists():
            example_path: typing.Final = self.config_path.with_suffix(self.config_path.suffix + ".example")
            if example_path.exists():
                return yaml.safe_load(example_path.read_text(encoding="utf-8")) or {}

            return self._bootstrap_raw_config()

        return yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def _bootstrap_raw_config(self) -> dict[str, Any]:
        provider_name: typing.Final = "bootstrap"
        return {
            "providers": {
                provider_name: {
                    "provider": "mock",
                    "models": [
                        {
                            "name": "bootstrap",
                            "api_key": "bootstrap",
                            "base_url": "",
                            "model": "bootstrap",
                        }
                    ],
                }
            },
            "feature_settings": {
                feature_name: {
                    "provider": provider_name,
                    "temperature": settings.llm_temperature,
                    "max_output_tokens": settings.llm_max_output_tokens,
                    "style": "default",
                }
                for feature_name in SUPPORTED_FEATURE_NAMES  # noqa: COP015
            },
        }

    def export_raw_config(self) -> dict[str, Any]:  # noqa: COP009
        snapshot: typing.Final = self._require_snapshot()
        return {
            "providers": {
                provider_name: {
                    "provider": provider_cfg.provider,
                    "models": [
                        {
                            "name": model.name,
                            "api_key": model.api_key,
                            "base_url": model.base_url,
                            "model": model.model,
                        }
                        for model in provider_cfg.models  # noqa: COP005, COP015
                    ],
                }
                for provider_name, provider_cfg in snapshot.providers.items()  # noqa: COP015
            },
            "feature_settings": {
                feature_name: {
                    "provider": feature_cfg.provider_name,
                    "temperature": feature_cfg.temperature,
                    "max_output_tokens": feature_cfg.max_output_tokens,
                    "style": feature_cfg.style,
                }
                for feature_name, feature_cfg in snapshot.feature_settings.items()  # noqa: COP015
            },
        }

    def list_provider_names(self) -> list[str]:
        return list(self._require_snapshot().providers.keys())

    def _provider_cache_key(self, provider_kind: str, endpoint: ModelEndpointConfig) -> str:  # noqa: COP009
        return f"{provider_kind}|{endpoint.base_url}|{endpoint.api_key}|{endpoint.model}"

    def validate_raw(self, raw: dict[str, Any]) -> None:  # noqa: COP006
        self._build_snapshot(raw)

    def build_snapshot_from_raw(self, raw: dict[str, Any]) -> LLMSnapshot:  # noqa: COP006
        return self._build_snapshot(raw)

    def reload_from_disk(self) -> None:  # noqa: COP009
        raw: typing.Final = self._read_raw_from_disk()  # noqa: COP005, COP011
        snapshot: typing.Final = self._build_snapshot(raw)  # noqa: COP011
        self._snapshot = snapshot
        self._last_reload_success = True
        self._last_reload_error = None

    def apply_snapshot(self, snapshot: LLMSnapshot) -> None:
        self._snapshot = snapshot
        self._last_reload_success = True
        self._last_reload_error = None

    def get_snapshot_metadata(self) -> dict[str, str | int | bool | None]:
        snapshot: typing.Final = self._require_snapshot()
        model_count: typing.Final = sum(len(provider.models) for provider in snapshot.providers.values())  # noqa: COP015
        return {
            "config_path": str(self.config_path),
            "loaded_at": snapshot.loaded_at.isoformat(),
            "reload_success": self._last_reload_success,
            "reload_error": self._last_reload_error,
            "providers_count": len(snapshot.providers),
            "models_count": model_count,
            "feature_settings_count": len(snapshot.feature_settings),
        }

    def _require_snapshot(self) -> LLMSnapshot:  # noqa: COP009
        if self._snapshot is None:
            raise RuntimeError("LLM registry snapshot is not initialized")
        return self._snapshot

    def get_feature_settings(self, feature_name: str) -> FeatureLLMSettings:
        feature_settings: typing.Final = self._require_snapshot().feature_settings
        if feature_name in feature_settings:
            return feature_settings[feature_name]
        return feature_settings["chat"]

    def get_provider_pool(self, provider_name: str) -> ProviderPoolConfig:
        providers: typing.Final = self._require_snapshot().providers  # noqa: COP011
        return providers[provider_name]

    def get_provider_instance(
        self,
        *,
        provider_kind: str,
        endpoint: ModelEndpointConfig,
    ) -> LLMProvider:
        instance_key: typing.Final = f"{provider_kind}:{endpoint.name}"
        cache_key: typing.Final = self._provider_cache_key(provider_kind, endpoint)

        cached: typing.Final = self._provider_instances.get(instance_key)  # noqa: COP005
        if cached is not None:
            old_cache_key, instance = cached
            if old_cache_key == cache_key:
                return instance

        provider: typing.Final = build_llm_provider_from_config(
            provider_name=provider_kind,
            api_key=endpoint.api_key,
            base_url=endpoint.base_url,
            model=endpoint.model,
        )
        self._provider_instances[instance_key] = (cache_key, provider)
        return provider

    def get_for_feature(self, feature_name: str) -> tuple[ProviderPoolConfig, FeatureLLMSettings]:
        feature_settings: typing.Final = self.get_feature_settings(feature_name)
        pool: typing.Final = self.get_provider_pool(feature_settings.provider_name)  # noqa: COP005, COP011
        return pool, feature_settings

    def get_for_feature_with_override(
        self,
        feature_name: str,
        *,
        provider_override: str | None = None,
        temperature_override: float | None = None,
        max_output_tokens_override: int | None = None,
        style_override: str | None = None,
    ) -> tuple[ProviderPoolConfig, FeatureLLMSettings]:
        base_settings: typing.Final = self.get_feature_settings(feature_name)
        provider_name: typing.Final = provider_override or base_settings.provider_name
        pool: typing.Final = self.get_provider_pool(provider_name)  # noqa: COP005

        effective_settings: typing.Final = FeatureLLMSettings(
            feature_name=feature_name,
            provider_name=provider_name,
            temperature=(temperature_override if temperature_override is not None else base_settings.temperature),
            max_output_tokens=(
                max_output_tokens_override
                if max_output_tokens_override is not None
                else base_settings.max_output_tokens
            ),
            style=(style_override if style_override is not None else base_settings.style),
        )
        return pool, effective_settings
