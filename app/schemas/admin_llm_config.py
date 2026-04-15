from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.llm_config_source import (
    SUPPORTED_FEATURE_NAMES,
    SUPPORTED_PROVIDER_TYPES,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
)


class AdminModelConfig(BaseModel):
    name: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    base_url: str = ""
    model: str = Field(min_length=1)


class AdminProviderConfig(BaseModel):
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    models: list[AdminModelConfig] = Field(default_factory=list)

    @field_validator("provider")
    @classmethod
    def validate_provider_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_PROVIDER_TYPES:
            raise ValueError(f"unsupported provider type: {value}")
        return normalized

    @field_validator("models")
    @classmethod
    def validate_models_not_empty(cls, value: list[AdminModelConfig]) -> list[AdminModelConfig]:
        if not value:
            raise ValueError("models list is empty")
        return value


class AdminFeatureSetting(BaseModel):
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    temperature: float
    max_output_tokens: int
    style: str = "default"

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        if value < TEMPERATURE_MIN or value > TEMPERATURE_MAX:
            raise ValueError("invalid temperature")
        return value

    @field_validator("max_output_tokens")
    @classmethod
    def validate_max_output_tokens(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("invalid max_output_tokens")
        return value


class AdminLLMConfig(BaseModel):
    providers: list[AdminProviderConfig] = Field(default_factory=list)
    feature_settings: list[AdminFeatureSetting] = Field(default_factory=list)

    @field_validator("providers")
    @classmethod
    def validate_providers_not_empty(cls, value: list[AdminProviderConfig]) -> list[AdminProviderConfig]:
        if not value:
            raise ValueError("providers list is empty")
        return value

    @model_validator(mode="after")
    def validate_unique_names_and_links(self) -> AdminLLMConfig:
        provider_names = [provider.name for provider in self.providers]
        if len(provider_names) != len(set(provider_names)):
            raise ValueError("duplicate provider name")

        for provider in self.providers:
            model_names = [model.name for model in provider.models]
            if len(model_names) != len(set(model_names)):
                raise ValueError(f"duplicate model name inside provider '{provider.name}'")

        known_provider_names = set(provider_names)
        for feature in self.feature_settings:
            if feature.provider not in known_provider_names:
                raise ValueError("provider references unknown provider")

        configured_features = [feature.name for feature in self.feature_settings]
        known_features = set(SUPPORTED_FEATURE_NAMES)
        if len(configured_features) != len(set(configured_features)):
            raise ValueError("duplicate feature name")
        unknown_features = [name for name in configured_features if name not in known_features]
        if unknown_features:
            raise ValueError(f"unknown feature name: {unknown_features[0]}")

        missing_features = [name for name in SUPPORTED_FEATURE_NAMES if name not in configured_features]
        if missing_features:
            raise ValueError(f"missing required feature setting: {missing_features[0]}")

        return self

    def to_raw_dict(self) -> dict:
        providers = {
            provider.name: {
                "provider": provider.provider,
                "models": [
                    {
                        "name": model.name,
                        "api_key": model.api_key,
                        "base_url": model.base_url,
                        "model": model.model,
                    }
                    for model in provider.models
                ],
            }
            for provider in self.providers
        }

        features = {
            feature.name: {
                "provider": feature.provider,
                "temperature": feature.temperature,
                "max_output_tokens": feature.max_output_tokens,
                "style": feature.style,
            }
            for feature in self.feature_settings
        }

        return {"providers": providers, "feature_settings": features}
