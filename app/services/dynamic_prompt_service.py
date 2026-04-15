from __future__ import annotations
import logging
import pathlib
import re
import typing

from sqlalchemy.orm import Session

import app.observability.trace_helpers
from app.config import settings
from app.prompt_store import PromptStore
from app.services.llm_execution_service import LLMExecutionService
from app.services.llm_registry import LLMRegistry
from app.services.style_prompt import StylePromptService
from app.text_utils import prepare_chat_text


logger = logging.getLogger(__name__)


class DynamicPromptService:
    def __init__(
        self,
        *,
        llm_registry: LLMRegistry,
        llm_executor: LLMExecutionService,
        prompts: PromptStore,
        style_prompt: StylePromptService,
    ) -> None:
        self.llm_registry = llm_registry
        self.llm_executor = llm_executor
        self.prompts = prompts
        self.style_prompt = style_prompt

    def _validate_prompt_name(self, prompt_name: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_\-]+", prompt_name):
            raise ValueError("Invalid prompt name")
        app.observability.trace_helpers.trace_success(
            "dynamic_prompt.validate.success", "dynamic prompt name validated", payload={"prompt_name": prompt_name}
        )
        return prompt_name

    def _resolve_prompt_names(self, prompt_name: str) -> tuple[str, str]:
        safe_name = self._validate_prompt_name(prompt_name)
        system_name = f"dynamic/{safe_name}_system.txt"
        template_name = f"dynamic/{safe_name}_template.txt"
        return system_name, template_name

    def _prompt_exists(self, relative_name: str) -> bool:
        prompt_path = pathlib.Path(settings.prompts_dir) / relative_name
        return prompt_path.exists() and prompt_path.is_file()

    async def generate(
        self,
        *,
        db: Session,
        prompt_name: str,
        user: str,
        data: dict[str, typing.Any],
        llm_provider_override: str | None = None,
        style_override: str | None = None,
        temperature_override: float | None = None,
        max_output_tokens_override: int | None = None,
    ) -> tuple[str, str]:
        try:
            system_name, template_name = self._resolve_prompt_names(prompt_name)
        except ValueError:
            logger.warning("Dynamic prompt name validation failed: %s", prompt_name)
            app.observability.trace_helpers.trace_failure(
                "dynamic_prompt.validate.failed", "dynamic prompt validation failed", error_code="validation_error"
            )
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback",
                "fallback path selected",
                payload={"reason": "invalid_prompt_name"},
            )
            return "fallback", ""

        if not self._prompt_exists(system_name) or not self._prompt_exists(template_name):
            logger.info(
                "Dynamic prompt files not found: prompt=%s system=%s template=%s",
                prompt_name,
                system_name,
                template_name,
            )
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.template.missing",
                "dynamic prompt files not found",
                payload={"prompt_name": prompt_name},
            )
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback",
                "fallback path selected",
                payload={"reason": "template_missing"},
            )
            return "fallback", ""

        dynamic_prompt_payload = data
        if not isinstance(dynamic_prompt_payload, dict):
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback",
                "fallback path selected",
                payload={"reason": "invalid_data"},
            )
            return "fallback", ""

        try:
            required_fields = self.prompts.get_required_fields(template_name)
        except ValueError as exc:
            logger.warning(
                "Dynamic prompt template validation failed: prompt=%s template=%s error=%s",
                prompt_name,
                template_name,
                str(exc),
            )
            app.observability.trace_helpers.trace_failure(
                "dynamic_prompt.template.invalid",
                "dynamic prompt template validation failed",
                error_code="prompt_template_invalid",
            )
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback",
                "fallback path selected",
                payload={"reason": "template_invalid"},
            )
            return "fallback", ""

        available_fields = {"user", *dynamic_prompt_payload.keys()}
        missing_fields = sorted(required_fields - available_fields)
        if missing_fields:
            logger.warning(
                "Dynamic prompt preflight failed: prompt=%s template=%s missing_fields=%s available_keys=%s",
                prompt_name,
                template_name,
                missing_fields,
                sorted(available_fields),
            )
            app.observability.trace_helpers.trace_failure(
                "dynamic_prompt.render.preflight_failed",
                "dynamic prompt preflight missing fields",
                payload={"missing_fields": missing_fields},
                error_code="prompt_render_preflight_error",
            )
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback", "fallback path selected", payload={"reason": "preflight_missing_field"}
            )
            return "fallback", ""

        pool, feature_cfg = self.llm_registry.get_for_feature_with_override(
            "dynamic_prompt",
            provider_override=llm_provider_override,
            style_override=style_override,
            temperature_override=temperature_override,
            max_output_tokens_override=max_output_tokens_override,
        )

        try:
            base_system_prompt = self.prompts.read(system_name)
            style_result = self.style_prompt.apply_style_with_resolution(
                base_system_prompt,
                feature_cfg.style,
            )
            system_prompt = style_result.system_prompt
            user_prompt = self.prompts.render(
                template_name,
                user=user,
                **dynamic_prompt_payload,
            )
        except KeyError as e:
            logger.warning(
                (
                    "Dynamic prompt render failed due to missing field after preflight: "
                    "prompt=%s missing=%s available_keys=%s"
                ),
                prompt_name,
                str(e),
                sorted(available_fields),
            )
            app.observability.trace_helpers.trace_failure(
                "dynamic_prompt.render.failed",
                "dynamic prompt render missing fields",
                payload={"missing": str(e)},
                error_code="prompt_render_error",
            )
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback",
                "fallback path selected",
                payload={"reason": "render_missing_field"},
            )
            return "fallback", ""
        except Exception:
            logger.exception("Dynamic prompt render failed: prompt=%s template=%s", prompt_name, template_name)
            app.observability.trace_helpers.trace_failure(
                "dynamic_prompt.render.failed", "dynamic prompt render failed", error_code="prompt_render_error"
            )
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback",
                "fallback path selected",
                payload={"reason": "render_failed"},
            )
            return "fallback", ""

        try:
            reply = await self.llm_executor.generate_text_with_pool(
                db=db,
                pool=pool,
                feature_settings=feature_cfg,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                style_resolution={
                    "requested_style": style_result.requested_style,
                    "applied_style": style_result.applied_style,
                    "style_resolution_status": style_result.style_resolution_status,
                    "style_resolution_reason": style_result.style_resolution_reason,
                },
            )
        except Exception:
            logger.exception("Dynamic prompt LLM call failed: prompt=%s", prompt_name)
            app.observability.trace_helpers.trace_failure(
                "dynamic_prompt.llm.failed", "dynamic prompt llm call failed", error_code="llm_error"
            )
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback",
                "fallback path selected",
                payload={"reason": "llm_failed"},
            )
            return "fallback", ""

        if not reply or not reply.strip():
            logger.info("Dynamic prompt returned empty reply: prompt=%s", prompt_name)
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback",
                "fallback path selected",
                payload={"reason": "empty_reply"},
            )
            return "fallback", ""

        reply = prepare_chat_text(reply, settings.twitch_message_limit).strip()

        if not reply:
            logger.info("Dynamic prompt reply became empty after trim: prompt=%s", prompt_name)
            app.observability.trace_helpers.trace_info(
                "dynamic_prompt.fallback",
                "fallback path selected",
                payload={"reason": "empty_after_trim"},
            )
            return "fallback", ""

        app.observability.trace_helpers.trace_success(
            "dynamic_prompt.llm.success",
            "dynamic prompt llm call succeeded",
            payload={"prompt_name": prompt_name, "reply_length": len(reply)},
        )
        return "success", reply
