import asyncio
import typing

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage
from app.prompt_store import PromptStore
from app.services.chat_memory import ChatMemoryService
from app.services.llm_execution_service import LLMExecutionService
from app.services.llm_registry import LLMRegistry
from app.services.provider_state_store import ProviderStateStore
from app.services.user_memory_service import UserMemoryService


EXPECTED_RETRY_ATTEMPTS = 2


def _build_service() -> UserMemoryService:
    llm_registry = LLMRegistry()
    llm_executor = LLMExecutionService(llm_registry=llm_registry, state_store=ProviderStateStore())
    return UserMemoryService(
        llm_registry=llm_registry,
        llm_executor=llm_executor,
        prompts=PromptStore(),
        chat_memory=ChatMemoryService(),
    )


def _save_two_messages(db_session: Session, memory_service: UserMemoryService) -> list[int]:
    chat_memory_service = memory_service.chat_memory
    first_message = chat_memory_service.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="люблю sci-fi",
        mentions_bot=False,
    )
    second_message = chat_memory_service.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="еще люблю sci-fi",
        mentions_bot=False,
    )
    db_session.commit()
    return [first_message.id, second_message.id]


def _load_messages(db_session: Session) -> list[ChatMessage]:
    return list(
        db_session.scalars(select(ChatMessage).where(ChatMessage.username == "alice").order_by(ChatMessage.id.asc()))
    )


def test_refresh_user_memory_if_needed_success_with_candidates(db_session: Session) -> None:  # noqa: COP009
    memory_service = _build_service()
    _save_two_messages(db_session, memory_service)

    async def generate_text_with_pool_stub(**_unused_kwargs: object) -> str:
        return '[{"kind":"preference","text":"любит sci-fi","evidence_count":2,"confidence":0.95}]'

    memory_service.llm_executor.generate_text_with_pool = generate_text_with_pool_stub  # type: ignore[method-assign]

    was_refreshed = asyncio.run(memory_service.refresh_user_memory_if_needed(db_session, "alice"))

    assert was_refreshed is True

    memory_items = memory_service.get_memory_items(db_session, "alice")
    assert len(memory_items) == 1
    assert memory_items[0].text == "любит sci-fi"

    stored_messages = _load_messages(db_session)
    assert all(one_message.is_memory_processed for one_message in stored_messages)
    assert all(one_message.memory_process_attempts == 1 for one_message in stored_messages)
    assert all(one_message.memory_last_error_code is None for one_message in stored_messages)


def test_refresh_user_memory_if_needed_success_empty_marks_processed(db_session: Session) -> None:  # noqa: COP009
    memory_service = _build_service()
    _save_two_messages(db_session, memory_service)

    async def generate_text_with_pool_stub(**_unused_kwargs: object) -> str:
        return "[]"

    memory_service.llm_executor.generate_text_with_pool = generate_text_with_pool_stub  # type: ignore[method-assign]

    was_refreshed = asyncio.run(memory_service.refresh_user_memory_if_needed(db_session, "alice"))

    assert was_refreshed is True
    assert memory_service.get_memory_items(db_session, "alice") == []

    stored_messages = _load_messages(db_session)
    assert all(one_message.is_memory_processed for one_message in stored_messages)
    assert all(one_message.memory_process_attempts == 1 for one_message in stored_messages)
    assert all(one_message.memory_last_error_code is None for one_message in stored_messages)


def test_refresh_user_memory_if_needed_invalid_json_keeps_unprocessed(db_session: Session) -> None:  # noqa: COP009
    memory_service = _build_service()
    _save_two_messages(db_session, memory_service)

    async def generate_text_with_pool_stub(**_unused_kwargs: object) -> str:
        return "not a json"

    memory_service.llm_executor.generate_text_with_pool = generate_text_with_pool_stub  # type: ignore[method-assign]

    was_refreshed = asyncio.run(memory_service.refresh_user_memory_if_needed(db_session, "alice"))

    assert was_refreshed is False

    stored_messages = _load_messages(db_session)
    assert all(not one_message.is_memory_processed for one_message in stored_messages)
    assert all(one_message.memory_process_attempts == 1 for one_message in stored_messages)
    assert all(one_message.memory_last_error_code == "memory_parse_error" for one_message in stored_messages)


def test_refresh_user_memory_if_needed_schema_error_keeps_unprocessed(db_session: Session) -> None:  # noqa: COP009
    memory_service = _build_service()
    _save_two_messages(db_session, memory_service)

    async def generate_text_with_pool_stub(**_unused_kwargs: object) -> str:
        return '[{"kind":"preference","text":"ok","confidence":0.9}]'

    memory_service.llm_executor.generate_text_with_pool = generate_text_with_pool_stub  # type: ignore[method-assign]

    was_refreshed = asyncio.run(memory_service.refresh_user_memory_if_needed(db_session, "alice"))

    assert was_refreshed is False

    stored_messages = _load_messages(db_session)
    assert all(not one_message.is_memory_processed for one_message in stored_messages)
    assert all(one_message.memory_process_attempts == 1 for one_message in stored_messages)
    assert all(one_message.memory_last_error_code == "memory_schema_error" for one_message in stored_messages)


def test_refresh_user_memory_if_needed_provider_error_keeps_unprocessed(db_session: Session) -> None:  # noqa: COP009
    memory_service = _build_service()
    _save_two_messages(db_session, memory_service)

    async def generate_text_with_pool_stub(**_unused_kwargs: object) -> typing.Never:
        raise RuntimeError("provider is down")

    memory_service.llm_executor.generate_text_with_pool = generate_text_with_pool_stub  # type: ignore[method-assign]

    was_refreshed = asyncio.run(memory_service.refresh_user_memory_if_needed(db_session, "alice"))

    assert was_refreshed is False

    stored_messages = _load_messages(db_session)
    assert all(not one_message.is_memory_processed for one_message in stored_messages)
    assert all(one_message.memory_process_attempts == 1 for one_message in stored_messages)
    assert all(one_message.memory_last_error_code == "memory_provider_error" for one_message in stored_messages)


def test_refresh_user_memory_if_needed_second_attempt_success_clears_error(db_session: Session) -> None:  # noqa: COP009
    memory_service = _build_service()
    _save_two_messages(db_session, memory_service)

    async def generate_text_with_pool_stub_fail(**_unused_kwargs: object) -> str:
        return "broken json"

    memory_service.llm_executor.generate_text_with_pool = generate_text_with_pool_stub_fail  # type: ignore[method-assign]

    assert asyncio.run(memory_service.refresh_user_memory_if_needed(db_session, "alice")) is False

    async def generate_text_with_pool_stub_success(**_unused_kwargs: object) -> str:
        return '[{"kind":"preference","text":"любит sci-fi","evidence_count":2,"confidence":0.95}]'

    memory_service.llm_executor.generate_text_with_pool = generate_text_with_pool_stub_success  # type: ignore[method-assign]

    second_refresh_result = asyncio.run(memory_service.refresh_user_memory_if_needed(db_session, "alice"))

    assert second_refresh_result is True

    stored_messages = _load_messages(db_session)
    assert all(one_message.is_memory_processed for one_message in stored_messages)
    assert all(one_message.memory_process_attempts == EXPECTED_RETRY_ATTEMPTS for one_message in stored_messages)
    assert all(one_message.memory_last_error_code is None for one_message in stored_messages)


def test_refresh_user_memory_if_needed_commits_once(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: COP009
    memory_service = _build_service()
    _save_two_messages(db_session, memory_service)

    async def generate_text_with_pool_stub(**_unused_kwargs: object) -> str:
        return '[{"kind":"preference","text":"любит sci-fi","evidence_count":2,"confidence":0.95}]'

    memory_service.llm_executor.generate_text_with_pool = generate_text_with_pool_stub  # type: ignore[method-assign]

    commit_call_count = 0
    original_commit_method = db_session.commit

    def count_commits() -> None:
        nonlocal commit_call_count
        commit_call_count += 1
        return original_commit_method()

    monkeypatch.setattr(db_session, "commit", count_commits)

    was_refreshed = asyncio.run(memory_service.refresh_user_memory_if_needed(db_session, "alice"))

    assert was_refreshed is True
    assert commit_call_count == 1


def test_refresh_user_memory_if_needed_rolls_back_on_error_before_mark_processed(db_session: Session) -> None:  # noqa: COP009
    memory_service = _build_service()
    _save_two_messages(db_session, memory_service)

    async def generate_text_with_pool_stub(**_unused_kwargs: object) -> str:
        return '[{"kind":"preference","text":"любит sci-fi","evidence_count":2,"confidence":0.95}]'

    memory_service.llm_executor.generate_text_with_pool = generate_text_with_pool_stub  # type: ignore[method-assign]

    def raise_trim_failure(*_unused_args: object, **_unused_kwargs: object) -> typing.Never:
        raise RuntimeError("trim failed")

    memory_service.trim_user_memory = raise_trim_failure  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="trim failed"):
        asyncio.run(memory_service.refresh_user_memory_if_needed(db_session, "alice"))

    assert memory_service.get_memory_items(db_session, "alice") == []

    stored_messages = _load_messages(db_session)
    assert all(not one_message.is_memory_processed for one_message in stored_messages)
    assert all(one_message.memory_process_attempts == 0 for one_message in stored_messages)
