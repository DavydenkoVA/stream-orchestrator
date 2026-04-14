import asyncio

from app.prompt_store import PromptStore
from app.services.dynamic_prompt_service import DynamicPromptService
from app.services.llm_execution_service import LLMExecutionService
from app.services.llm_registry import LLMRegistry
from app.services.provider_state_store import ProviderStateStore
from app.services.style_prompt import StylePromptService
from app.services.style_registry import StyleRegistry


def _build_service() -> DynamicPromptService:
    registry = LLMRegistry()
    style_registry = StyleRegistry()
    prompt_store = PromptStore()
    executor = LLMExecutionService(llm_registry=registry, state_store=ProviderStateStore())
    return DynamicPromptService(
        llm_registry=registry,
        llm_executor=executor,
        prompts=prompt_store,
        style_prompt=StylePromptService(style_registry),
    )


def test_dynamic_prompt_returns_success_when_prompt_and_data_are_valid(db_session) -> None:
    service = _build_service()

    result, message = asyncio.run(
        service.generate(
            db=db_session,
            prompt_name="test",
            user="alice",
            data={"loot": "gold"},
        )
    )

    assert result == "success"
    assert message


def test_dynamic_prompt_returns_fallback_for_missing_prompt_files(db_session) -> None:
    service = _build_service()

    result, message = asyncio.run(
        service.generate(
            db=db_session,
            prompt_name="missing",
            user="alice",
            data={"loot": "gold"},
        )
    )

    assert result == "fallback"
    assert message == ""


def test_dynamic_prompt_returns_fallback_for_invalid_name(db_session) -> None:
    service = _build_service()

    result, message = asyncio.run(
        service.generate(
            db=db_session,
            prompt_name="../hack",
            user="alice",
            data={"loot": "gold"},
        )
    )

    assert result == "fallback"
    assert message == ""


def test_dynamic_prompt_returns_fallback_when_template_data_missing(db_session) -> None:
    service = _build_service()

    result, message = asyncio.run(
        service.generate(
            db=db_session,
            prompt_name="test",
            user="alice",
            data={},
        )
    )

    assert result == "fallback"
    assert message == ""
