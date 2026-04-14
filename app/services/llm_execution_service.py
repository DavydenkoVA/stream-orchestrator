from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.integrations.llm.base import LLMProvider
from app.services.llm_registry import FeatureLLMSettings, LLMRegistry, ModelEndpointConfig, ProviderPoolConfig
from app.services.provider_state_store import ProviderStateStore
from app.observability.trace_helpers import trace_failure, trace_info, trace_success

logger = logging.getLogger(__name__)


class LLMExecutionService:
    def __init__(
        self,
        *,
        llm_registry: LLMRegistry,
        state_store: ProviderStateStore,
    ) -> None:
        self.llm_registry = llm_registry
        self.state_store = state_store

    def _build_attempt_order(
        self,
        *,
        pool: ProviderPoolConfig,
        current_model_name: str | None,
    ) -> list[ModelEndpointConfig]:
        if not pool.models:
            return []

        by_name = {item.name: item for item in pool.models}

        if not current_model_name or current_model_name not in by_name:
            return list(pool.models)

        current = by_name[current_model_name]
        rest = [item for item in pool.models if item.name != current_model_name]
        return [current, *rest]

    def _is_retryable_exception(self, exc: Exception) -> bool:
        name = exc.__class__.__name__.lower()
        text = str(exc).lower()

        retryable_markers = [
            "timeout",
            "rate limit",
            "quota",
            "connection",
            "authenticationerror",
            "apierror",
            "internalservererror",
            "serviceunavailableerror",
            "ratelimiterror",
        ]

        if any(marker in name for marker in retryable_markers):
            return True

        if any(marker in text for marker in retryable_markers):
            return True

        return False

    async def generate_text_with_pool(
        self,
        *,
        db: Session,
        pool: ProviderPoolConfig,
        feature_settings: FeatureLLMSettings,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        current_model_name = self.state_store.get_current_model_name(db, pool.name)
        trace_info(
            "llm.generate.start",
            "starting llm generation",
            payload={"provider": pool.provider, "pool": pool.name, "feature": feature_settings.feature_name},
        )
        ordered_models = self._build_attempt_order(
            pool=pool,
            current_model_name=current_model_name,
        )

        if not ordered_models:
            raise RuntimeError(f"Provider pool '{pool.name}' has no models")

        last_exc: Exception | None = None
        attempted_names: list[str] = []

        for endpoint in ordered_models:
            attempted_names.append(endpoint.name)
            llm: LLMProvider = self.llm_registry.get_provider_instance(
                provider_kind=pool.provider,
                endpoint=endpoint,
            )

            try:
                reply = await llm.generate_text(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=feature_settings.temperature,
                    max_output_tokens=feature_settings.max_output_tokens,
                )

                self.state_store.set_current_model_name(db, pool.name, endpoint.name)
                db.commit()

                if endpoint.name != current_model_name:
                    trace_info(
                        "llm.pool.switch",
                        "llm pool switched active model",
                        payload={
                            "provider": pool.provider,
                            "pool": pool.name,
                            "old_model": current_model_name,
                            "new_model": endpoint.name,
                        },
                    )
                    logger.warning(
                        "LLM pool switched active model: provider=%s old=%s new=%s",
                        pool.name,
                        current_model_name,
                        endpoint.name,
                    )

                trace_success(
                    "llm.generate.success",
                    "llm generation succeeded",
                    payload={"provider": pool.provider, "model": endpoint.name, "reply_length": len(reply or "")},
                )
                return reply

            except Exception as exc:
                last_exc = exc
                trace_failure(
                    "llm.model.failed",
                    "llm model failed",
                    payload={"provider": pool.provider, "model": endpoint.name},
                    error_code="llm_error",
                )
                logger.warning(
                    "LLM model failed: provider=%s model_name=%s feature=%s error=%s",
                    pool.name,
                    endpoint.name,
                    feature_settings.feature_name,
                    exc,
                )

                if not self._is_retryable_exception(exc):
                    raise

                continue

        logger.error(
            "LLM pool exhausted: provider=%s attempted=%s",
            pool.name,
            attempted_names,
        )
        trace_failure(
            "llm.generate.failed",
            "llm provider pool exhausted",
            payload={"provider": pool.provider, "attempted_models": attempted_names},
            error_code="llm_error",
        )

        if last_exc is not None:
            raise last_exc

        raise RuntimeError(f"Provider pool '{pool.name}' exhausted with no reply")
