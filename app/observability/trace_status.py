from __future__ import annotations

from collections.abc import Iterable

TRACE_RUN_STATUS_RUNNING = "running"
TRACE_RUN_STATUS_SUCCESS = "success"
TRACE_RUN_STATUS_FAILED = "failed"
TRACE_RUN_STATUS_DEGRADED = "degraded"

TRACE_RUN_ALLOWED_STATUSES: tuple[str, ...] = (
    TRACE_RUN_STATUS_RUNNING,
    TRACE_RUN_STATUS_SUCCESS,
    TRACE_RUN_STATUS_FAILED,
    TRACE_RUN_STATUS_DEGRADED,
)

TRACE_STATUS_FILTER_ALL = "all"

_TRACE_STATUS_TONE_BY_STATUS: dict[str, str] = {
    TRACE_RUN_STATUS_SUCCESS: "success",
    TRACE_RUN_STATUS_FAILED: "failure",
    TRACE_RUN_STATUS_DEGRADED: "warning",
    TRACE_RUN_STATUS_RUNNING: "info",
}


class TraceStatusValidationError(ValueError):
    def __init__(self, status: str, allowed: Iterable[str]) -> None:
        allowed_values = tuple(allowed)
        super().__init__(
            f"Unknown status '{status}'. Allowed values: {', '.join(allowed_values)}"
        )
        self.status = status
        self.allowed_values = allowed_values


def normalize_status_filter(status: str | None) -> str | None:
    """Normalize trace runs status filter.

    Returns None when there is no status filtering (None/empty/'all').
    """
    if status is None:
        return None

    normalized = status.strip().lower()
    if not normalized or normalized == TRACE_STATUS_FILTER_ALL:
        return None

    if normalized not in TRACE_RUN_ALLOWED_STATUSES:
        raise TraceStatusValidationError(normalized, TRACE_RUN_ALLOWED_STATUSES)

    return normalized


def trace_status_tone(status: str | None) -> str:
    normalized = (status or "").strip().lower()
    return _TRACE_STATUS_TONE_BY_STATUS.get(normalized, "neutral")
