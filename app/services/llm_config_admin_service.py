from __future__ import annotations
import dataclasses
import pathlib
import re
import tempfile
import typing

import pydantic
import yaml

from app.schemas.admin_llm_config import AdminLLMConfig
from app.services.style_registry import StyleRegistry


if typing.TYPE_CHECKING:
    import collections.abc

    from app.services.llm_registry import LLMRegistry


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class AdminValidationResult:
    valid: bool  # noqa: COP004
    errors: list[str]  # noqa: COP004
    config: AdminLLMConfig | None = None  # noqa: COP004
    raw: dict[str, typing.Any] | None = None  # noqa: COP004


@typing.final
class LLMConfigAdminService:
    PROVIDER_PATTERN = re.compile(r"^providers\[(\d+)\]\[(name|provider)\]$")
    MODEL_PATTERN = re.compile(r"^providers\[(\d+)\]\[models\]\[(\d+)\]\[(name|api_key|base_url|model)\]$")
    FEATURE_PATTERN = re.compile(r"^feature_settings\[(\d+)\]\[(name|provider|temperature|max_output_tokens|style)\]$")

    def __init__(self, registry: LLMRegistry, style_registry: StyleRegistry | None = None) -> None:
        self.registry = registry
        self.style_registry = style_registry or StyleRegistry()

    def read_raw_config(self) -> dict[str, typing.Any]:
        config_path = pathlib.Path(self.registry.config_path)
        if not config_path.exists():
            return {}
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    def read_styles_raw(self, styles_path: str | pathlib.Path) -> dict[str, typing.Any]:
        styles_config_path = pathlib.Path(styles_path)
        if not styles_config_path.exists():
            return {}
        return yaml.safe_load(styles_config_path.read_text(encoding="utf-8")) or {}

    def parse_form_data(self, form_data: dict[str, str]) -> dict[str, typing.Any]:
        provider_map: dict[int, dict[str, typing.Any]] = {}
        feature_map: dict[int, dict[str, typing.Any]] = {}

        for form_field_name, form_field_value in form_data.items():
            provider_match = self.PROVIDER_PATTERN.match(form_field_name)
            if provider_match:
                provider_index = int(provider_match.group(1))
                provider_map.setdefault(provider_index, {"models": {}})[provider_match.group(2)] = str(
                    form_field_value
                ).strip()
                continue

            model_match = self.MODEL_PATTERN.match(form_field_name)
            if model_match:
                provider_index = int(model_match.group(1))
                model_index = int(model_match.group(2))
                typing.cast(
                    "dict[int, dict[str, str]]",
                    provider_map.setdefault(provider_index, {"models": {}}).setdefault("models", {}),
                ).setdefault(model_index, {})[model_match.group(3)] = str(form_field_value).strip()
                continue

            feature_match = self.FEATURE_PATTERN.match(form_field_name)
            if feature_match:
                feature_map.setdefault(int(feature_match.group(1)), {})[feature_match.group(2)] = str(
                    form_field_value
                ).strip()

        ordered_providers: list[dict[str, typing.Any]] = []
        for one_provider_index in sorted(provider_map.keys()):
            provider_record = provider_map[one_provider_index]
            models_map = typing.cast("dict[int, dict[str, str]]", provider_record.get("models", {}))
            ordered_models = [models_map[one_model_index] for one_model_index in sorted(models_map.keys())]
            ordered_providers.append(
                {
                    "name": provider_record.get("name", ""),
                    "provider": provider_record.get("provider", ""),
                    "models": ordered_models,
                }
            )

        ordered_features = [feature_map[one_feature_index] for one_feature_index in sorted(feature_map.keys())]
        return {
            "providers": ordered_providers,
            "feature_settings": ordered_features,
        }

    def validate_form_data(self, form_data: dict[str, str]) -> AdminValidationResult:
        parsed_raw_payload = self.parse_form_data(form_data)

        try:
            validated_config = AdminLLMConfig.model_validate(parsed_raw_payload)
            normalized_raw_payload = validated_config.to_raw_dict()
            self.registry.validate_raw(normalized_raw_payload)
            style_reference_errors = self._validate_style_references(normalized_raw_payload)
            if style_reference_errors:
                return AdminValidationResult(valid=False, errors=style_reference_errors)
            return AdminValidationResult(valid=True, errors=[], config=validated_config, raw=normalized_raw_payload)
        except pydantic.ValidationError as validation_error:
            return AdminValidationResult(
                valid=False,
                errors=[self._humanize_error(one_error) for one_error in validation_error.errors()],
            )
        except ValueError as value_error:
            return AdminValidationResult(valid=False, errors=[str(value_error)])

    def apply_form_data(self, form_data: dict[str, str]) -> AdminValidationResult:
        validation_result = self.validate_form_data(form_data)
        if not validation_result.valid or validation_result.raw is None:
            return validation_result

        config_path = pathlib.Path(self.registry.config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_payload = yaml.safe_dump(
            validation_result.raw,
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
            temp_file_path = pathlib.Path(temp_file.name)

        try:
            temp_file_path.replace(config_path)
        finally:
            if temp_file_path.exists():
                temp_file_path.unlink(missing_ok=True)

        self.registry.apply_snapshot(self.registry.build_snapshot_from_raw(validation_result.raw))
        return validation_result

    def _validate_style_references(self, raw_payload: dict[str, typing.Any]) -> list[str]:
        style_validation_errors: list[str] = []
        for one_feature_name, one_feature_config in raw_payload.get("feature_settings", {}).items():
            style_value = one_feature_config.get("style")
            style_error = self.style_registry.validate_style_reference(
                style_value if isinstance(style_value, str) else None
            )
            if style_error is not None:
                style_validation_errors.append(f"feature '{one_feature_name}': {style_error}")
        return style_validation_errors

    @staticmethod
    def _humanize_error(error_payload: collections.abc.Mapping[str, typing.Any]) -> str:  # noqa: C901, PLR0911, PLR0912, COP009
        error_location = error_payload.get("loc", ())
        error_message = str(error_payload.get("msg", "validation error"))
        lowered_error_message = error_message.lower()

        if "providers list is empty" in lowered_error_message:
            return "providers list is empty"
        if "models list is empty" in lowered_error_message:
            return "models list is empty"
        if "duplicate provider name" in lowered_error_message:
            return "duplicate provider name"
        if "duplicate model name inside provider" in lowered_error_message:
            return error_message
        if "provider references unknown provider" in lowered_error_message:
            return "provider references unknown provider"
        if "unsupported provider type" in lowered_error_message:
            return error_message
        if "unknown feature name" in lowered_error_message:
            return error_message
        if "missing required feature setting" in lowered_error_message:
            return error_message
        if "duplicate feature name" in lowered_error_message:
            return "duplicate feature name"
        if "invalid temperature" in lowered_error_message:
            return "invalid temperature"
        if "invalid max_output_tokens" in lowered_error_message:
            return "invalid max_output_tokens"

        if any(one_location_part == "api_key" for one_location_part in error_location) and (
            "at least 1 character" in lowered_error_message
        ):
            return "api_key is empty"
        if any(one_location_part == "name" for one_location_part in error_location) and (
            "at least 1 character" in lowered_error_message
        ):
            return "name is empty"
        if any(one_location_part == "model" for one_location_part in error_location) and (
            "at least 1 character" in lowered_error_message
        ):
            return "model is empty"

        return error_message
