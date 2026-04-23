from app.services.llm_registry import LLMRegistry


EXPECTED_MODELS_COUNT = 2
EXPECTED_TEMPERATURE = 0.2
EXPECTED_MAX_OUTPUT_TOKENS = 77


def test_llm_registry_loads_pool_and_feature_settings() -> None:
    registry = LLMRegistry()

    pool, feature = registry.get_for_feature("chat")

    assert pool.name == "primary"
    assert len(pool.models) == EXPECTED_MODELS_COUNT
    assert feature.feature_name == "chat"
    assert feature.provider_name == "primary"


def test_llm_registry_applies_overrides() -> None:
    registry = LLMRegistry()

    pool, feature = registry.get_for_feature_with_override(
        "chat",
        style_override="strict",
        temperature_override=0.2,
        max_output_tokens_override=77,
    )

    assert pool.name == "primary"
    assert feature.style == "strict"
    assert feature.temperature == EXPECTED_TEMPERATURE
    assert feature.max_output_tokens == EXPECTED_MAX_OUTPUT_TOKENS


def test_llm_registry_reuses_cached_provider_instance() -> None:
    registry = LLMRegistry()
    pool = registry.get_provider_pool("primary")  # noqa: COP005
    endpoint = pool.models[0]

    first = registry.get_provider_instance(provider_kind=pool.provider, endpoint=endpoint)  # noqa: COP005
    second = registry.get_provider_instance(provider_kind=pool.provider, endpoint=endpoint)  # noqa: COP005

    assert first is second
