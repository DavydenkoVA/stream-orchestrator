from __future__ import annotations
import json
import typing
from typing import TYPE_CHECKING, Any  # noqa: COP002

from sqlalchemy import Select, select

from app.models.trace_event import TraceEvent
from app.models.trace_run import TraceRun
from app.observability.trace_status import (
    normalize_status_filter,
    style_resolution_result,
    style_resolution_tone,
    trace_event_tone,
    trace_status_tone,
)


if TYPE_CHECKING:
    from datetime import datetime  # noqa: COP002

    from sqlalchemy.orm import Session


@typing.final
class TraceReadService:
    """Read-only access layer for trace runs and events used by admin UI/API."""

    def list_runs(
        self,
        db: Session,  # noqa: COP006
        *,
        limit: int = 50,  # noqa: COP006
        stream_id: str | None = None,
        status: str | None = None,  # noqa: COP006
    ) -> list[dict[str, Any]]:
        query: Select[tuple[TraceRun]] = select(TraceRun)  # noqa: COP005
        if stream_id:
            query = query.where(TraceRun.stream_id == stream_id)  # noqa: COP005
        normalized_status: typing.Final = normalize_status_filter(status)
        if normalized_status:
            query = query.where(TraceRun.status == normalized_status)  # noqa: COP005

        query = query.order_by(TraceRun.started_at.desc(), TraceRun.id.desc()).limit(limit)  # noqa: COP005
        runs: typing.Final = list(db.scalars(query).all())  # noqa: COP005, COP011
        return [self._serialize_run(run) for run in runs]  # noqa: COP005, COP015

    def get_run_detail(self, db: Session, run_id: str) -> dict[str, Any] | None:  # noqa: COP006
        run: typing.Final = db.scalar(select(TraceRun).where(TraceRun.trace_id == run_id))  # noqa: COP005
        if run is None:
            return None

        events_query: typing.Final = (
            select(TraceEvent)
            .where(TraceEvent.trace_run_id == run.id)
            .order_by(TraceEvent.seq_no.asc(), TraceEvent.id.asc())
        )
        events: typing.Final = list(db.scalars(events_query).all())  # noqa: COP005, COP011
        serialized_events: typing.Final = [self._serialize_event(event) for event in events]  # noqa: COP005, COP015
        style_resolution: typing.Final = self._derive_style_resolution(serialized_events)
        run_payload: typing.Final = self._serialize_run(run)
        run_payload.update(style_resolution)

        return {
            "run": run_payload,
            "events": serialized_events,
        }

    def _serialize_run(self, run: TraceRun) -> dict[str, Any]:  # noqa: COP006, COP009
        started_at: typing.Final = self._iso(run.started_at)
        finished_at: typing.Final = self._iso(run.finished_at)

        duration_ms: int | None = None
        if run.started_at and run.finished_at:
            duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)

        return {
            "id": run.trace_id,
            "request_id": run.request_id,
            "route": run.route,
            "stream_id": run.stream_id,
            "status": run.status,
            "status_tone": trace_status_tone(run.status),
            "error_code": run.error_code,
            "summary": run.summary,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
        }

    def _serialize_event(self, event: TraceEvent) -> dict[str, Any]:  # noqa: COP006, COP009
        payload = None  # noqa: COP005
        if event.payload_json:
            try:
                payload = json.loads(event.payload_json)  # noqa: COP005
            except json.JSONDecodeError:
                payload = event.payload_json  # noqa: COP005

        return {
            "id": str(event.id),
            "seq_no": event.seq_no,
            "timestamp": self._iso(event.timestamp),
            "kind": event.step,
            "status": event.status,
            "level": event.level,
            "tone": trace_event_tone(status=event.status, level=event.level, step=event.step),
            "style_resolution": self._serialize_style_resolution(payload),
            "message": event.message,
            "payload": payload,
        }

    @staticmethod
    def _serialize_style_resolution(payload: Any) -> dict[str, str] | None:  # noqa: ANN401, COP006, COP009
        if not isinstance(payload, dict):
            return None

        requested_style: typing.Final = payload.get("requested_style")
        applied_style: typing.Final = payload.get("applied_style") or payload.get("style")
        resolution_status: typing.Final = payload.get("style_resolution_status")
        resolution_reason: typing.Final = payload.get("style_resolution_reason")

        requested: typing.Final = requested_style.strip() if isinstance(requested_style, str) else ""
        applied: typing.Final = applied_style.strip() if isinstance(applied_style, str) else ""  # noqa: COP005
        status: typing.Final = resolution_status.strip() if isinstance(resolution_status, str) else ""  # noqa: COP005
        reason: typing.Final = resolution_reason.strip() if isinstance(resolution_reason, str) else ""  # noqa: COP005

        if not requested and not applied and not status and not reason:
            return None

        return {
            "requested": requested or "unknown",
            "applied": applied or "unknown",
            "status": status or "unknown",
            "reason": reason,
            "tone": style_resolution_tone(
                requested_style=requested or None,
                applied_style=applied or None,
                status=status or None,
                reason=reason or None,
            ),
            "result": style_resolution_result(
                requested_style=requested or None,
                applied_style=applied or None,
                status=status or None,
                reason=reason or None,
            ),
        }

    @staticmethod
    def _derive_style_resolution(events: list[dict[str, Any]]) -> dict[str, str]:  # noqa: C901, COP006, COP009
        requested_values: typing.Final[set[str]] = set()
        applied_values: typing.Final[set[str]] = set()
        status_values: typing.Final[set[str]] = set()
        reason_values: typing.Final[set[str]] = set()

        for event in events:  # noqa: COP015
            payload = event.get("payload")  # noqa: COP005
            if not isinstance(payload, dict):
                continue

            requested_style = payload.get("requested_style")
            if isinstance(requested_style, str) and requested_style.strip():
                requested_values.add(requested_style.strip())

            applied_style = payload.get("applied_style")
            if isinstance(applied_style, str) and applied_style.strip():
                applied_values.add(applied_style.strip())

            legacy_style = payload.get("style")
            if isinstance(legacy_style, str) and legacy_style.strip():
                applied_values.add(legacy_style.strip())

            resolution_status = payload.get("style_resolution_status")
            if isinstance(resolution_status, str) and resolution_status.strip():
                status_values.add(resolution_status.strip())

            resolution_reason = payload.get("style_resolution_reason")
            if isinstance(resolution_reason, str) and resolution_reason.strip():
                reason_values.add(resolution_reason.strip())

        def _single_or_multiple(values: set[str]) -> str | None:  # noqa: COP009
            if not values:
                return None
            if len(values) == 1:
                return next(iter(values))
            return "multiple"

        derived: typing.Final[dict[str, str]] = {}  # noqa: COP005
        requested: typing.Final = _single_or_multiple(requested_values)
        applied: typing.Final = _single_or_multiple(applied_values)  # noqa: COP005
        resolution_status = _single_or_multiple(status_values)
        resolution_reason = _single_or_multiple(reason_values)

        if requested is not None:
            derived["requested_style"] = requested
        if applied is not None:
            derived["applied_style"] = applied
        if resolution_status is not None:
            derived["style_resolution_status"] = resolution_status
        if resolution_reason is not None:
            derived["style_resolution_reason"] = resolution_reason

        return derived

    @staticmethod
    def _iso(value: datetime | None) -> str | None:  # noqa: COP009
        if value is None:
            return None
        return value.isoformat()
