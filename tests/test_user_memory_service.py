import asyncio

from sqlalchemy import select

from app.models.chat import ChatMessage
from app.prompt_store import PromptStore
from app.services.chat_memory import ChatMemoryService
from app.services.llm_execution_service import LLMExecutionService
from app.services.llm_registry import LLMRegistry
from app.services.provider_state_store import ProviderStateStore
from app.services.user_memory_service import UserMemoryService


def _build_service() -> UserMemoryService:
    registry = LLMRegistry()
    executor = LLMExecutionService(llm_registry=registry, state_store=ProviderStateStore())
    return UserMemoryService(
        llm_registry=registry,
        llm_executor=executor,
        prompts=PromptStore(),
        chat_memory=ChatMemoryService(),
    )


def _save_two_messages(db_session, service: UserMemoryService) -> list[int]:
    chat = service.chat_memory
    first = chat.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="люблю sci-fi",
        mentions_bot=False,
    )
    second = chat.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="еще люблю sci-fi",
        mentions_bot=False,
    )
    db_session.commit()
    return [first.id, second.id]


def _load_messages(db_session) -> list[ChatMessage]:
    stmt = select(ChatMessage).where(ChatMessage.username == "alice").order_by(ChatMessage.id.asc())
    return list(db_session.scalars(stmt))


def test_refresh_user_memory_if_needed_success_with_candidates(db_session) -> None:
    service = _build_service()
    _save_two_messages(db_session, service)

    async def fake_generate_text_with_pool(**kwargs):
        return '[{"kind":"preference","text":"любит sci-fi","evidence_count":2,"confidence":0.95}]'

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool  # type: ignore[method-assign]

    refreshed = asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))

    assert refreshed is True

    memories = service.get_memory_items(db_session, "alice")
    assert len(memories) == 1
    assert memories[0].text == "любит sci-fi"

    messages = _load_messages(db_session)
    assert all(msg.is_memory_processed for msg in messages)
    assert all(msg.memory_process_attempts == 1 for msg in messages)
    assert all(msg.memory_last_error_code is None for msg in messages)


def test_refresh_user_memory_if_needed_success_empty_marks_processed(db_session) -> None:
    service = _build_service()
    _save_two_messages(db_session, service)

    async def fake_generate_text_with_pool(**kwargs):
        return "[]"

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool  # type: ignore[method-assign]

    refreshed = asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))

    assert refreshed is True
    assert service.get_memory_items(db_session, "alice") == []

    messages = _load_messages(db_session)
    assert all(msg.is_memory_processed for msg in messages)
    assert all(msg.memory_process_attempts == 1 for msg in messages)
    assert all(msg.memory_last_error_code is None for msg in messages)


def test_refresh_user_memory_if_needed_invalid_json_keeps_unprocessed(db_session) -> None:
    service = _build_service()
    _save_two_messages(db_session, service)

    async def fake_generate_text_with_pool(**kwargs):
        return "not a json"

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool  # type: ignore[method-assign]

    refreshed = asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))

    assert refreshed is False

    messages = _load_messages(db_session)
    assert all(not msg.is_memory_processed for msg in messages)
    assert all(msg.memory_process_attempts == 1 for msg in messages)
    assert all(msg.memory_last_error_code == "memory_parse_error" for msg in messages)


def test_refresh_user_memory_if_needed_schema_error_keeps_unprocessed(db_session) -> None:
    service = _build_service()
    _save_two_messages(db_session, service)

    async def fake_generate_text_with_pool(**kwargs):
        return '[{"kind":"preference","text":"ok","confidence":0.9}]'

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool  # type: ignore[method-assign]

    refreshed = asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))

    assert refreshed is False

    messages = _load_messages(db_session)
    assert all(not msg.is_memory_processed for msg in messages)
    assert all(msg.memory_process_attempts == 1 for msg in messages)
    assert all(msg.memory_last_error_code == "memory_schema_error" for msg in messages)


def test_refresh_user_memory_if_needed_provider_error_keeps_unprocessed(db_session) -> None:
    service = _build_service()
    _save_two_messages(db_session, service)

    async def fake_generate_text_with_pool(**kwargs):
        raise RuntimeError("provider is down")

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool  # type: ignore[method-assign]

    refreshed = asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))

    assert refreshed is False

    messages = _load_messages(db_session)
    assert all(not msg.is_memory_processed for msg in messages)
    assert all(msg.memory_process_attempts == 1 for msg in messages)
    assert all(msg.memory_last_error_code == "memory_provider_error" for msg in messages)


def test_refresh_user_memory_if_needed_second_attempt_success_clears_error(db_session) -> None:
    service = _build_service()
    _save_two_messages(db_session, service)

    async def fake_generate_text_with_pool_fail(**kwargs):
        return "broken json"

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool_fail  # type: ignore[method-assign]

    first_refresh = asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))
    assert first_refresh is False

    async def fake_generate_text_with_pool_success(**kwargs):
        return '[{"kind":"preference","text":"любит sci-fi","evidence_count":2,"confidence":0.95}]'

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool_success  # type: ignore[method-assign]

    second_refresh = asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))

    assert second_refresh is True

    messages = _load_messages(db_session)
    assert all(msg.is_memory_processed for msg in messages)
    assert all(msg.memory_process_attempts == 2 for msg in messages)
    assert all(msg.memory_last_error_code is None for msg in messages)


def test_refresh_user_memory_if_needed_commits_once(db_session, monkeypatch) -> None:
    service = _build_service()
    _save_two_messages(db_session, service)

    async def fake_generate_text_with_pool(**kwargs):
        return '[{"kind":"preference","text":"любит sci-fi","evidence_count":2,"confidence":0.95}]'

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool  # type: ignore[method-assign]

    commit_calls = 0
    original_commit = db_session.commit

    def counting_commit():
        nonlocal commit_calls
        commit_calls += 1
        return original_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)

    refreshed = asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))

    assert refreshed is True
    assert commit_calls == 1


def test_refresh_user_memory_if_needed_rolls_back_on_error_before_mark_processed(db_session) -> None:
    service = _build_service()
    _save_two_messages(db_session, service)

    async def fake_generate_text_with_pool(**kwargs):
        return '[{"kind":"preference","text":"любит sci-fi","evidence_count":2,"confidence":0.95}]'

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool  # type: ignore[method-assign]

    def fail_trim(*args, **kwargs):
        raise RuntimeError("trim failed")

    service.trim_user_memory = fail_trim  # type: ignore[method-assign]

    try:
        asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "trim failed" in str(exc)

    memories = service.get_memory_items(db_session, "alice")
    assert memories == []

    messages = _load_messages(db_session)
    assert all(not msg.is_memory_processed for msg in messages)
    assert all(msg.memory_process_attempts == 0 for msg in messages)
