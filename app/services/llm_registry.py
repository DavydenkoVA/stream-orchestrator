from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.config import settings
from app.integrations.llm.base import LLMProvider
from app.integrations.llm.factory import build_llm_provider_from_config


@dataclass(slots=True)
class ProviderProfile:
    name: str
    provider: str
    api_key: str
    base_url: str
    model: str


@dataclass(slots=True)
class FeatureLLMSettings:
    feature_name: str
    provider_name: str
    temperature: float
    max_output_tokens: int


class LLMRegistry:
    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = Path(config_path or settings.llm_profiles_config_path)
        self._provider_instances: dict[str, tuple[str, LLMProvider]] = {}

    def _load(self) -> tuple[dict[str, ProviderProfile], dict[str, FeatureLLMSettings]]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"LLM profiles config not found: {self.config_path}")

        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

        providers_raw = raw.get("providers", {})
        feature_settings_raw = raw.get("feature_settings", {})

        if not providers_raw:
            raise ValueError("llm_profiles.yml: 'providers' section is empty")

        providers: dict[str, ProviderProfile] = {}
        feature_settings: dict[str, FeatureLLMSettings] = {}

        for name, cfg in providers_raw.items():
            api_key_env = str(cfg.get("api_key_env", "")).strip()
            api_key = os.getenv(api_key_env, "") if api_key_env else ""

            providers[name] = ProviderProfile(
                name=name,
                provider=str(cfg["provider"]).strip(),
                api_key=api_key,
                base_url=str(cfg.get("base_url", "")).strip(),
                model=str(cfg["model"]).strip(),
            )

        for feature_name, cfg in feature_settings_raw.items():
            provider_name = str(cfg["provider"]).strip()

            if provider_name not in providers:
                raise ValueError(
                    f"llm_profiles.yml: feature '{feature_name}' refers to unknown provider '{provider_name}'"
                )

            feature_settings[feature_name] = FeatureLLMSettings(
                feature_name=feature_name,
                provider_name=provider_name,
                temperature=float(cfg.get("temperature", settings.llm_temperature)),
                max_output_tokens=int(
                    cfg.get("max_output_tokens", settings.llm_max_output_tokens)
                ),
            )

        if "chat" not in feature_settings:
            first_provider = next(iter(providers.keys()))
            feature_settings["chat"] = FeatureLLMSettings(
                feature_name="chat",
                provider_name=first_provider,
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
            )

        return providers, feature_settings

    def _provider_cache_key(self, profile: ProviderProfile) -> str:
        return f"{profile.provider}|{profile.base_url}|{profile.api_key}|{profile.model}"

    def get_feature_settings(self, feature_name: str) -> FeatureLLMSettings:
        _, feature_settings = self._load()
        if feature_name in feature_settings:
            return feature_settings[feature_name]
        return feature_settings["chat"]

    def get_provider(self, provider_name: str) -> LLMProvider:
        providers, _ = self._load()
        profile = providers[provider_name]
        cache_key = self._provider_cache_key(profile)

        cached = self._provider_instances.get(provider_name)
        if cached is not None:
            old_cache_key, instance = cached
            if old_cache_key == cache_key:
                return instance

        provider = build_llm_provider_from_config(
            provider_name=profile.provider,
            api_key=profile.api_key,
            base_url=profile.base_url,
            model=profile.model,
        )
        self._provider_instances[provider_name] = (cache_key, provider)
        return provider

    def get_for_feature(self, feature_name: str) -> tuple[LLMProvider, FeatureLLMSettings]:
        feature_settings = self.get_feature_settings(feature_name)
        provider = self.get_provider(feature_settings.provider_name)
        return provider, feature_settings

    def get_for_feature_with_override(
        self,
        feature_name: str,
        *,
        provider_override: str | None = None,
        temperature_override: float | None = None,
        max_output_tokens_override: int | None = None,
    ) -> tuple[LLMProvider, FeatureLLMSettings]:
        base_settings = self.get_feature_settings(feature_name)

        provider_name = provider_override or base_settings.provider_name
        provider = self.get_provider(provider_name)

        effective_settings = FeatureLLMSettings(
            feature_name=feature_name,
            provider_name=provider_name,
            temperature=(
                temperature_override
                if temperature_override is not None
                else base_settings.temperature
            ),
            max_output_tokens=(
                max_output_tokens_override
                if max_output_tokens_override is not None
                else base_settings.max_output_tokens
            ),
        )

        return provider, effective_settings