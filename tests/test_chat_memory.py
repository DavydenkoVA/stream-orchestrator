import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage
from app.services.chat_memory import ChatMemoryService


MAX_MEMORY_ATTEMPTS = 3
PENDING_MEMORY_ATTEMPTS = 2


def test_save_message_does_not_commit_and_assigns_id_via_flush(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ChatMemoryService()

    commit_calls = 0
    original_commit = db_session.commit

    def counting_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1
        return original_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)

    message = service.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="hello",
        mentions_bot=False,
    )

    assert message.id is not None
    assert commit_calls == 0


def test_save_message_persists_only_after_external_commit(db_session: Session) -> None:
    service = ChatMemoryService()

    service.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="hello",
        mentions_bot=False,
    )
    db_session.commit()

    stmt = select(ChatMessage).where(ChatMessage.username == "alice")
    rows = list(db_session.scalars(stmt))
    assert len(rows) == 1


def test_mark_messages_memory_extraction_attempted_skips_processed_messages(db_session: Session) -> None:
    service = ChatMemoryService()

    processed = service.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="done",
        mentions_bot=False,
    )
    pending = service.save_message(
        db_session,
        stream_id="s1",
        username="alice",
        text="pending",
        mentions_bot=False,
    )
    db_session.flush()

    processed.is_memory_processed = True
    processed.memory_process_attempts = 3
    pending.is_memory_processed = False
    pending.memory_process_attempts = 1
    db_session.commit()

    service.mark_messages_memory_extraction_attempted(
        db_session,
        message_ids=[processed.id, pending.id],
        error_code="memory_parse_error",
    )
    db_session.commit()

    stmt = select(ChatMessage).where(ChatMessage.id.in_([processed.id, pending.id]))
    rows = {row.id: row for row in db_session.scalars(stmt)}

    processed_row = rows[processed.id]
    pending_row = rows[pending.id]

    assert processed_row.is_memory_processed is True
    assert processed_row.memory_process_attempts == MAX_MEMORY_ATTEMPTS
    assert processed_row.memory_last_error_code is None

    assert pending_row.is_memory_processed is False
    assert pending_row.memory_process_attempts == PENDING_MEMORY_ATTEMPTS
    assert pending_row.memory_last_error_code == "memory_parse_error"
