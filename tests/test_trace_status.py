from app.observability.trace_status import (
    TRACE_RUN_STATUS_DEGRADED,
    TRACE_RUN_STATUS_FAILED,
    TRACE_RUN_STATUS_RUNNING,
    TRACE_RUN_STATUS_SUCCESS,
    normalize_status_filter,
    style_resolution_result,
    style_resolution_tone,
    trace_event_tone,
    trace_status_tone,
)


def test_trace_status_tone_mapping() -> None:
    assert trace_status_tone(TRACE_RUN_STATUS_SUCCESS) == "success"
    assert trace_status_tone(TRACE_RUN_STATUS_FAILED) == "failure"
    assert trace_status_tone(TRACE_RUN_STATUS_DEGRADED) == "warning"
    assert trace_status_tone(TRACE_RUN_STATUS_RUNNING) == "info"
    assert trace_status_tone("legacy_status") == "neutral"


def test_normalize_status_filter_supports_all() -> None:
    assert normalize_status_filter(None) is None
    assert normalize_status_filter("") is None
    assert normalize_status_filter("all") is None
    assert normalize_status_filter("failed") == "failed"


def test_trace_event_tone_mapping_priority() -> None:
    assert trace_event_tone(status="success", level="INFO", step="chat_message.save.success") == "success"
    assert trace_event_tone(status="failed", level="INFO", step="llm.model.failed") == "failure"
    assert trace_event_tone(status="degraded", level="WARNING", step="route.result") == "warning"
    assert trace_event_tone(status=None, level="ERROR", step="request.finish") == "failure"
    assert trace_event_tone(status="info", level="INFO", step="request.start") == "info"
    assert trace_event_tone(status=None, level=None, step="legacy.unknown") == "neutral"


def test_style_resolution_tone_and_result_mapping() -> None:
    assert style_resolution_tone(
        requested_style="dark",
        applied_style="dark",
        status="success",
        reason="requested_applied",
    ) == "success"
    assert style_resolution_result(
        requested_style="dark",
        applied_style="dark",
        status="success",
        reason="requested_applied",
    ) == "applied"

    assert style_resolution_tone(
        requested_style="random",
        applied_style="sarcastic",
        status="success",
        reason="random_resolved",
    ) == "success"
    assert style_resolution_result(
        requested_style="random",
        applied_style="sarcastic",
        status="success",
        reason="random_resolved",
    ) == "resolved"

    assert style_resolution_tone(
        requested_style="default",
        applied_style="default",
        status="success",
        reason="default_used",
    ) == "success"

    assert style_resolution_tone(
        requested_style="daark",
        applied_style="default",
        status="fallback",
        reason="style_not_found",
    ) == "failure"
    assert style_resolution_result(
        requested_style="daark",
        applied_style="default",
        status="fallback",
        reason="style_not_found",
    ) == "fallback"

    assert style_resolution_tone(
        requested_style=None,
        applied_style=None,
        status=None,
        reason=None,
    ) == "neutral"
