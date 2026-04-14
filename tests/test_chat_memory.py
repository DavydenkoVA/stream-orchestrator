from sqlalchemy import select

from app.models.chat import ChatMessage
from app.services.chat_memory import ChatMemoryService


def test_save_message_does_not_commit_and_assigns_id_via_flush(db_session, monkeypatch) -> None:
    service = ChatMemoryService()

    commit_calls = 0
    original_commit = db_session.commit

    def counting_commit():
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


def test_save_message_persists_only_after_external_commit(db_session) -> None:
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
