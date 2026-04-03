import asyncio
from types import SimpleNamespace

from app.config import settings
from app.services.features import ChatRequest, DossierFeatureHandler, FeatureSelector, WeeklyMoviesFeatureHandler
from app.services.router import RouterService


class _AlwaysFalseHandler:
    route_name = "never"

    def matches(self, request: ChatRequest) -> bool:
        return False


class _AlwaysTrueHandler:
    route_name = "always"

    def matches(self, request: ChatRequest) -> bool:
        return True


class _SecondTrueHandler:
    route_name = "second"

    def matches(self, request: ChatRequest) -> bool:
        return True


def test_feature_selector_returns_first_matching_handler() -> None:
    selector = FeatureSelector([_AlwaysFalseHandler(), _AlwaysTrueHandler(), _SecondTrueHandler()])
    request = ChatRequest(
        stream_id="stream-1",
        username="viewer",
        text="@bot привет",
        mentions_bot=True,
    )

    selected = selector.select(request)

    assert isinstance(selected, _AlwaysTrueHandler)


def test_dossier_handler_extracts_target_and_matches_case_insensitive() -> None:
    handler = DossierFeatureHandler()

    assert handler.extract_target("Сделай досье на @Test_User") == "Test_User"
    assert handler.extract_target("досье на viewer123") == "viewer123"
    assert handler.extract_target("просто чат") is None

    request = ChatRequest(
        stream_id="stream-1",
        username="author",
        text="ДОСЬЕ НА @Viewer123",
        mentions_bot=False,
    )
    assert handler.matches(request) is True


def test_dossier_handler_returns_conflict_message_for_bot_target() -> None:
    handler = DossierFeatureHandler()
    request = ChatRequest(
        stream_id="stream-1",
        username="viewer",
        text=f"досье на @{settings.bot_username}",
        mentions_bot=False,
    )
    context = SimpleNamespace()

    response = asyncio.run(handler.handle(context, request))

    assert response.route == "dossier"
    assert "конфликт интересов" in response.reply_text.lower()


def test_weekly_movies_handler_matches_known_triggers() -> None:
    handler = WeeklyMoviesFeatureHandler()

    request = ChatRequest(
        stream_id="stream-1",
        username="viewer",
        text="Ребят, что смотрим на этой неделе?",
        mentions_bot=False,
    )
    request_without_trigger = ChatRequest(
        stream_id="stream-1",
        username="viewer",
        text="как дела",
        mentions_bot=False,
    )

    assert handler.matches(request) is True
    assert handler.matches(request_without_trigger) is False


def test_router_handle_chat_reply_ignores_bot_role() -> None:
    router = RouterService()
    was_ingested = {"value": False}

    def _fake_ingest_chat_event(*args, **kwargs):
        was_ingested["value"] = True

    router.ingest_chat_event = _fake_ingest_chat_event  # type: ignore[method-assign]

    reply, route = asyncio.run(
        router.handle_chat_reply(
            db=None,
            stream_id="stream-1",
            username="stream_bot",
            text="service message",
            mentions_bot=False,
            role="bot",
        )
    )

    assert was_ingested["value"] is True
    assert reply == ""
    assert route == "ignored"


def test_router_normalizes_usernames_and_extracts_dossier_target() -> None:
    router = RouterService()

    assert router.normalize_username("  @TeSt_User  ") == "test_user"
    assert router.extract_dossier_target("сделай досье на @Target_1") == "Target_1"
    assert router.extract_dossier_target("обычное сообщение") is None
