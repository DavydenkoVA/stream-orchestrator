import asyncio
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.chat import ChatMessage
from app.services.file_readers.weekly_movies import WeeklyMoviesFileService
from app.services.router import RouterService


class SpyLLM:
    def __init__(self, reply_text: str = "LLM_REPLY") -> None:
        self.reply_text = reply_text
        self.calls: list[dict] = []

    async def generate_text(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.reply_text


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def test_chat_feature_selected_on_bot_mention() -> None:
    db = make_session()
    llm = SpyLLM("chat answer")
    service = RouterService(llm=llm)

    reply_text, route = asyncio.run(
        service.handle_chat_reply(
            db,
            stream_id="s1",
            username="viewer1",
            text="@bot привет",
            mentions_bot=True,
        )
    )

    assert route == "chat"
    assert reply_text == "chat answer"
    assert len(llm.calls) == 1


def test_weekly_movies_has_priority_over_mention(tmp_path: Path) -> None:
    db = make_session()
    llm = SpyLLM("movies answer")
    service = RouterService(llm=llm)

    weekly_file = tmp_path / "weekly_movies.txt"
    weekly_file.write_text("Film 1\nFilm 2", encoding="utf-8")
    service.weekly_movies = WeeklyMoviesFileService(str(weekly_file))

    reply_text, route = asyncio.run(
        service.handle_chat_reply(
            db,
            stream_id="s1",
            username="viewer1",
            text="@bot что смотрим на этой неделе?",
            mentions_bot=True,
        )
    )

    assert route == "weekly_movies"
    assert reply_text == "movies answer"
    assert len(llm.calls) == 1


def test_dossier_feature_selected_and_uses_target_data() -> None:
    db = make_session()
    llm = SpyLLM("dossier answer")
    service = RouterService(llm=llm)

    # minimum context for dossier generation (2+ messages for target user)
    db.add_all(
        [
            ChatMessage(
                stream_id="s1",
                username="target_user",
                role="viewer",
                text="первое сообщение",
                mentions_bot=False,
            ),
            ChatMessage(
                stream_id="s1",
                username="target_user",
                role="viewer",
                text="второе сообщение",
                mentions_bot=False,
            ),
        ]
    )
    db.commit()

    reply_text, route = asyncio.run(
        service.handle_chat_reply(
            db,
            stream_id="s1",
            username="viewer1",
            text="сделай досье на @target_user",
            mentions_bot=False,
        )
    )

    assert route == "dossier"
    assert reply_text == "dossier answer"
    assert len(llm.calls) == 1


def test_ignored_when_no_feature_matches() -> None:
    db = make_session()
    llm = SpyLLM("should not be used")
    service = RouterService(llm=llm)

    reply_text, route = asyncio.run(
        service.handle_chat_reply(
            db,
            stream_id="s1",
            username="viewer1",
            text="просто сообщение в чат",
            mentions_bot=False,
        )
    )

    assert route == "ignored"
    assert reply_text == ""
    assert llm.calls == []
