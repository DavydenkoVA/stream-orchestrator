import asyncio

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


def test_extract_memory_candidates_filters_invalid_payload(db_session) -> None:
    service = _build_service()

    async def fake_generate_text_with_pool(**kwargs):
        return '[{"kind":"preference","text":"любит рогалики","evidence_count":2,"confidence":0.9}, {"kind":"bad","text":"x","confidence":1.0}]'

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool  # type: ignore[method-assign]

    items = asyncio.run(
        service.extract_memory_candidates(
            db_session,
            username="alice",
            messages=["я люблю рогалики"],
        )
    )

    assert len(items) == 1
    assert items[0]["kind"] == "preference"


def test_refresh_user_memory_if_needed_merges_and_marks_messages(db_session) -> None:
    service = _build_service()
    chat = service.chat_memory

    chat.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="люблю sci-fi",
        mentions_bot=False,
    )
    chat.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="еще люблю sci-fi",
        mentions_bot=False,
    )

    async def fake_generate_text_with_pool(**kwargs):
        return '[{"kind":"preference","text":"любит sci-fi","evidence_count":2,"confidence":0.95}]'

    service.llm_executor.generate_text_with_pool = fake_generate_text_with_pool  # type: ignore[method-assign]

    refreshed = asyncio.run(service.refresh_user_memory_if_needed(db_session, "alice"))

    assert refreshed is True

    memories = service.get_memory_items(db_session, "alice")
    assert len(memories) == 1
    assert memories[0].text == "любит sci-fi"

    unprocessed = chat.count_unprocessed_user_messages(db_session, username="alice")
    assert unprocessed == 0


def test_refresh_user_memory_if_needed_commits_once(db_session, monkeypatch) -> None:
    service = _build_service()
    chat = service.chat_memory

    chat.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="люблю sci-fi",
        mentions_bot=False,
    )
    chat.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="еще люблю sci-fi",
        mentions_bot=False,
    )
    db_session.commit()

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
    chat = service.chat_memory

    chat.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="люблю sci-fi",
        mentions_bot=False,
    )
    chat.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="еще люблю sci-fi",
        mentions_bot=False,
    )
    db_session.commit()

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

    unprocessed = chat.count_unprocessed_user_messages(db_session, username="alice")
    assert unprocessed == 2
