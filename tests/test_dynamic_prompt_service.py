import asyncio
from pathlib import Path

from pytest import MonkeyPatch
from sqlalchemy.orm import Session

from app.config import settings
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


def test_dynamic_prompt_returns_success_when_prompt_and_data_are_valid(db_session: Session) -> None:
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


def test_dynamic_prompt_returns_fallback_for_missing_prompt_files(db_session: Session) -> None:
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


def test_dynamic_prompt_returns_fallback_for_invalid_name(db_session: Session) -> None:
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


def test_dynamic_prompt_returns_fallback_when_template_data_missing_without_llm_call(
    db_session: Session,
    monkeypatch: MonkeyPatch,
) -> None:
    service = _build_service()
    llm_called = False

    async def _fake_generate_text_with_pool(**kwargs: object) -> str:
        nonlocal llm_called
        llm_called = True
        return "unexpected"

    monkeypatch.setattr(service.llm_executor, "generate_text_with_pool", _fake_generate_text_with_pool)

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
    assert llm_called is False


def test_dynamic_prompt_returns_fallback_for_invalid_template_without_llm_call(
    db_session: Session,
    monkeypatch: MonkeyPatch,
) -> None:
    broken_system = Path(settings.prompts_dir) / "dynamic" / "broken_system.txt"
    broken_template = Path(settings.prompts_dir) / "dynamic" / "broken_template.txt"
    broken_system.write_text("dynamic system", encoding="utf-8")
    broken_template.write_text("broken {", encoding="utf-8")

    service = _build_service()
    llm_called = False

    async def _fake_generate_text_with_pool(**kwargs: object) -> str:
        nonlocal llm_called
        llm_called = True
        return "unexpected"

    monkeypatch.setattr(service.llm_executor, "generate_text_with_pool", _fake_generate_text_with_pool)

    result, message = asyncio.run(
        service.generate(
            db=db_session,
            prompt_name="broken",
            user="alice",
            data={"loot": "gold"},
        )
    )

    assert result == "fallback"
    assert message == ""
    assert llm_called is False


def test_dynamic_prompt_allows_extra_data_fields(db_session: Session) -> None:
    service = _build_service()

    result, message = asyncio.run(
        service.generate(
            db=db_session,
            prompt_name="test",
            user="alice",
            data={"loot": "gold", "extra": "value"},
        )
    )

    assert result == "success"
    assert message


def test_dynamic_prompt_user_field_is_available_without_data_key(db_session: Session) -> None:
    user_only_system = Path(settings.prompts_dir) / "dynamic" / "user_only_system.txt"
    user_only_template = Path(settings.prompts_dir) / "dynamic" / "user_only_template.txt"
    user_only_system.write_text("dynamic system", encoding="utf-8")
    user_only_template.write_text("hello {user}", encoding="utf-8")

    service = _build_service()

    result, message = asyncio.run(
        service.generate(
            db=db_session,
            prompt_name="user_only",
            user="alice",
            data={},
        )
    )

    assert result == "success"
    assert message
