import asyncio

from app.services.llm_execution_service import LLMExecutionService
from app.services.llm_registry import FeatureLLMSettings, LLMRegistry
from app.services.provider_state_store import ProviderStateStore


class _FakeProvider:
    def __init__(self, name: str, fail: bool) -> None:
        self.name = name
        self.fail = fail
        self.calls = 0

    async def generate_text(self, **kwargs) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} timeout")
        return f"ok:{self.name}"


def _build_executor() -> tuple[LLMRegistry, LLMExecutionService, ProviderStateStore]:
    registry = LLMRegistry()
    store = ProviderStateStore()
    executor = LLMExecutionService(llm_registry=registry, state_store=store)
    return registry, executor, store


def test_failover_uses_second_model_and_persists_state(db_session, monkeypatch) -> None:
    registry, executor, store = _build_executor()
    pool, feature = registry.get_for_feature("chat")

    first = _FakeProvider("model_a", fail=True)
    second = _FakeProvider("model_b", fail=False)

    providers = {"model_a": first, "model_b": second}
    monkeypatch.setattr(
        registry,
        "get_provider_instance",
        lambda provider_kind, endpoint: providers[endpoint.name],
    )

    reply = asyncio.run(
        executor.generate_text_with_pool(
            db=db_session,
            pool=pool,
            feature_settings=feature,
            system_prompt="sys",
            user_prompt="user",
        )
    )

    assert reply == "ok:model_b"
    assert first.calls == 1
    assert second.calls == 1
    assert store.get_current_model_name(db_session, pool.name) == "model_b"


def test_if_current_model_removed_attempt_starts_from_first(db_session, monkeypatch) -> None:
    registry, executor, store = _build_executor()
    pool, feature = registry.get_for_feature("chat")
    store.set_current_model_name(db_session, pool.name, "removed_model")

    calls: list[str] = []

    class _OnlyFirst:
        async def generate_text(self, **kwargs):
            calls.append("model_a")
            return "ok:model_a"

    monkeypatch.setattr(
        registry,
        "get_provider_instance",
        lambda provider_kind, endpoint: _OnlyFirst(),
    )

    reply = asyncio.run(
        executor.generate_text_with_pool(
            db=db_session,
            pool=pool,
            feature_settings=feature,
            system_prompt="sys",
            user_prompt="user",
        )
    )

    assert reply == "ok:model_a"
    assert calls == ["model_a"]


def test_if_all_models_fail_each_model_is_tried_once(db_session, monkeypatch) -> None:
    registry, executor, _ = _build_executor()
    pool, feature = registry.get_for_feature("chat")

    first = _FakeProvider("model_a", fail=True)
    second = _FakeProvider("model_b", fail=True)

    providers = {"model_a": first, "model_b": second}
    monkeypatch.setattr(
        registry,
        "get_provider_instance",
        lambda provider_kind, endpoint: providers[endpoint.name],
    )

    try:
        asyncio.run(
            executor.generate_text_with_pool(
                db=db_session,
                pool=pool,
                feature_settings=feature,
                system_prompt="sys",
                user_prompt="user",
            )
        )
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "timeout" in str(exc)

    assert first.calls == 1
    assert second.calls == 1


def test_provider_state_store_roundtrip(db_session) -> None:
    store = ProviderStateStore()

    assert store.get_current_model_name(db_session, "primary") is None

    store.set_current_model_name(db_session, "primary", "model_a")
    assert store.get_current_model_name(db_session, "primary") == "model_a"

    store.set_current_model_name(db_session, "primary", "model_b")
    assert store.get_current_model_name(db_session, "primary") == "model_b"
