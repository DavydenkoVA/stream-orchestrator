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
        super().__init__(f"Unknown status '{status}'. Allowed values: {', '.join(allowed_values)}")
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


def trace_event_tone(
    *,
    status: str | None,
    level: str | None,
    step: str | None = None,
) -> str:
    normalized_status = (status or "").strip().lower()
    normalized_level = (level or "").strip().upper()
    normalized_step = (step or "").strip().lower()

    if normalized_status in {"success"}:
        return "success"
    if normalized_status in {"failed", "failure", "error"}:
        return "failure"
    if normalized_status in {"degraded", "warning", "warn", "partial"}:
        return "warning"
    if normalized_status in {"running", "in_progress", "started"}:
        return "info"

    if normalized_level == "ERROR":
        return "failure"
    if normalized_level == "WARNING":
        return "warning"
    if normalized_level == "INFO" and (
        normalized_status == "info"
        or normalized_step.endswith(".start")
        or normalized_step.endswith(".running")
        or "start" in normalized_step
        or "running" in normalized_step
    ):
        return "info"

    return "neutral"


_STYLE_RESOLUTION_SUCCESS_REASONS = {
    "requested_applied",
    "random_resolved",
    "default_used",
}
_STYLE_RESOLUTION_FAILURE_REASONS = {
    "style_not_found",
    "invalid_style_fallback",
    "random_no_candidates_defaulted",
}


def style_resolution_tone(
    *,
    requested_style: str | None,
    applied_style: str | None,
    status: str | None,
    reason: str | None,
) -> str:
    normalized_status = (status or "").strip().lower()
    normalized_reason = (reason or "").strip().lower()
    requested = (requested_style or "").strip().lower()
    applied = (applied_style or "").strip().lower()

    if normalized_status in {"fallback", "failed"}:
        return "failure"
    if normalized_reason in _STYLE_RESOLUTION_FAILURE_REASONS:
        return "failure"

    if normalized_status == "success" and (
        normalized_reason in _STYLE_RESOLUTION_SUCCESS_REASONS or normalized_reason == ""
    ):
        return "success"
    if normalized_reason in _STYLE_RESOLUTION_SUCCESS_REASONS:
        return "success"

    if requested and applied and requested == applied:
        return "success"
    if requested and applied and requested != applied:
        return "failure"

    return "neutral"


def style_resolution_result(
    *,
    requested_style: str | None,
    applied_style: str | None,
    status: str | None,
    reason: str | None,
) -> str:
    normalized_status = (status or "").strip().lower()
    normalized_reason = (reason or "").strip().lower()
    requested = (requested_style or "").strip().lower()
    applied = (applied_style or "").strip().lower()

    if normalized_status in {"fallback", "failed"} or normalized_reason in _STYLE_RESOLUTION_FAILURE_REASONS:
        return "fallback"
    if normalized_status == "success" and normalized_reason == "random_resolved":
        return "resolved"
    if normalized_status == "success" and (requested == applied or normalized_reason == "requested_applied"):
        return "applied"
    if normalized_status == "success":
        return "resolved"
    return "unknown"
