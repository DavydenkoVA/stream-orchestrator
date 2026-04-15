from app.observability.trace_status import (
    TRACE_RUN_STATUS_DEGRADED,
    TRACE_RUN_STATUS_FAILED,
    TRACE_RUN_STATUS_RUNNING,
    TRACE_RUN_STATUS_SUCCESS,
    normalize_status_filter,
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
