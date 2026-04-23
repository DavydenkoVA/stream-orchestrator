from __future__ import annotations
import types
import typing


if typing.TYPE_CHECKING:
    from collections.abc import Iterable


TRACE_RUN_STATUS_RUNNING: typing.Final = "running"
TRACE_RUN_STATUS_SUCCESS: typing.Final = "success"
TRACE_RUN_STATUS_FAILED: typing.Final = "failed"
TRACE_RUN_STATUS_DEGRADED: typing.Final = "degraded"

TRACE_RUN_ALLOWED_STATUSES: typing.Final[tuple[str, ...]] = (
    TRACE_RUN_STATUS_RUNNING,
    TRACE_RUN_STATUS_SUCCESS,
    TRACE_RUN_STATUS_FAILED,
    TRACE_RUN_STATUS_DEGRADED,
)

TRACE_STATUS_FILTER_ALL: typing.Final = "all"

_TRACE_STATUS_TONE_BY_STATUS: typing.Final = types.MappingProxyType(
    {
        TRACE_RUN_STATUS_SUCCESS: "success",
        TRACE_RUN_STATUS_FAILED: "failure",
        TRACE_RUN_STATUS_DEGRADED: "warning",
        TRACE_RUN_STATUS_RUNNING: "info",
    }
)


@typing.final
class TraceStatusValidationError(ValueError):
    def __init__(self, status_value: str, allowed_statuses: Iterable[str]) -> None:
        allowed_values: typing.Final = tuple(allowed_statuses)
        super().__init__(f"Unknown status '{status_value}'. Allowed values: {', '.join(allowed_values)}")
        self.status = status_value
        self.allowed_values = allowed_values


def normalize_status_filter(status_value: str | None) -> str | None:  # noqa: COP009
    """Normalize trace runs status filter.

    Returns None when there is no status filtering (None/empty/'all').
    """
    if status_value is None:
        return None

    normalized_status: typing.Final = status_value.strip().lower()
    if not normalized_status or normalized_status == TRACE_STATUS_FILTER_ALL:
        return None

    if normalized_status not in TRACE_RUN_ALLOWED_STATUSES:
        raise TraceStatusValidationError(normalized_status, TRACE_RUN_ALLOWED_STATUSES)

    return normalized_status


def resolve_trace_status_tone(status_value: str | None) -> str:
    return _TRACE_STATUS_TONE_BY_STATUS.get((status_value or "").strip().lower(), "neutral")


def resolve_trace_event_tone(  # noqa: PLR0911
    *,
    status_value: str | None,
    level_value: str | None,
    step_value: str | None = None,
) -> str:
    normalized_status: typing.Final = (status_value or "").strip().lower()
    normalized_level: typing.Final = (level_value or "").strip().upper()
    normalized_step: typing.Final = (step_value or "").strip().lower()

    if normalized_status == "success":
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
        or normalized_step.endswith((".start", ".running"))
        or "start" in normalized_step
        or "running" in normalized_step
    ):
        return "info"

    return "neutral"


_STYLE_RESOLUTION_SUCCESS_REASONS: typing.Final = {
    "requested_applied",
    "random_resolved",
    "default_used",
}
_STYLE_RESOLUTION_FAILURE_REASONS: typing.Final = {
    "style_not_found",
    "invalid_style_fallback",
    "random_no_candidates_defaulted",
}


def resolve_style_resolution_tone(  # noqa: PLR0911
    *,
    requested_style: str | None,
    applied_style: str | None,
    status_value: str | None,
    reason_value: str | None,
) -> str:
    normalized_status: typing.Final = (status_value or "").strip().lower()
    normalized_reason: typing.Final = (reason_value or "").strip().lower()
    normalized_requested_style: typing.Final = (requested_style or "").strip().lower()
    normalized_applied_style: typing.Final = (applied_style or "").strip().lower()

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

    if (
        normalized_requested_style
        and normalized_applied_style
        and normalized_requested_style == normalized_applied_style
    ):
        return "success"
    if (
        normalized_requested_style
        and normalized_applied_style
        and normalized_requested_style != normalized_applied_style
    ):
        return "failure"

    return "neutral"


def resolve_style_resolution_result(
    *,
    requested_style: str | None,
    applied_style: str | None,
    status_value: str | None,
    reason_value: str | None,
) -> str:
    normalized_status: typing.Final = (status_value or "").strip().lower()
    normalized_reason: typing.Final = (reason_value or "").strip().lower()
    normalized_requested_style: typing.Final = (requested_style or "").strip().lower()
    normalized_applied_style: typing.Final = (applied_style or "").strip().lower()

    if normalized_status in {"fallback", "failed"} or normalized_reason in _STYLE_RESOLUTION_FAILURE_REASONS:
        return "fallback"
    if normalized_status == "success" and normalized_reason == "random_resolved":
        return "resolved"
    if normalized_status == "success" and (
        normalized_requested_style == normalized_applied_style or normalized_reason == "requested_applied"
    ):
        return "applied"
    if normalized_status == "success":
        return "resolved"
    return "unknown"


def trace_status_tone(status: str | None) -> str:  # noqa: COP009,COP006
    return resolve_trace_status_tone(status)


def trace_event_tone(  # noqa: COP009
    *,
    status: str | None,  # noqa: COP006
    level: str | None,  # noqa: COP006
    step: str | None = None,  # noqa: COP006
) -> str:
    return resolve_trace_event_tone(status_value=status, level_value=level, step_value=step)


def style_resolution_tone(  # noqa: COP009
    *,
    requested_style: str | None,
    applied_style: str | None,
    status: str | None,  # noqa: COP006
    reason: str | None,  # noqa: COP006
) -> str:
    return resolve_style_resolution_tone(
        requested_style=requested_style,
        applied_style=applied_style,
        status_value=status,
        reason_value=reason,
    )


def style_resolution_result(  # noqa: COP009
    *,
    requested_style: str | None,
    applied_style: str | None,
    status: str | None,  # noqa: COP006
    reason: str | None,  # noqa: COP006
) -> str:
    return resolve_style_resolution_result(
        requested_style=requested_style,
        applied_style=applied_style,
        status_value=status,
        reason_value=reason,
    )
