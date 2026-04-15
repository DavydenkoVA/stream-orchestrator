from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.trace_event import TraceEvent
from app.models.trace_run import TraceRun
from app.observability.trace_status import normalize_status_filter, trace_event_tone, trace_status_tone


class TraceReadService:
    """Read-only access layer for trace runs and events used by admin UI/API."""

    def list_runs(
        self,
        db: Session,
        *,
        limit: int = 50,
        stream_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        query: Select[tuple[TraceRun]] = select(TraceRun)
        if stream_id:
            query = query.where(TraceRun.stream_id == stream_id)
        normalized_status = normalize_status_filter(status)
        if normalized_status:
            query = query.where(TraceRun.status == normalized_status)

        query = query.order_by(TraceRun.started_at.desc(), TraceRun.id.desc()).limit(limit)
        runs = list(db.scalars(query).all())
        return [self._serialize_run(run) for run in runs]

    def get_run_detail(self, db: Session, run_id: str) -> dict[str, Any] | None:
        run = db.scalar(select(TraceRun).where(TraceRun.trace_id == run_id))
        if run is None:
            return None

        events_query = (
            select(TraceEvent)
            .where(TraceEvent.trace_run_id == run.id)
            .order_by(TraceEvent.seq_no.asc(), TraceEvent.id.asc())
        )
        events = list(db.scalars(events_query).all())
        serialized_events = [self._serialize_event(event) for event in events]
        applied_style = self._derive_applied_style(serialized_events)
        run_payload = self._serialize_run(run)
        if applied_style is not None:
            run_payload["applied_style"] = applied_style

        return {
            "run": run_payload,
            "events": serialized_events,
        }

    def _serialize_run(self, run: TraceRun) -> dict[str, Any]:
        started_at = self._iso(run.started_at)
        finished_at = self._iso(run.finished_at)

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

    def _serialize_event(self, event: TraceEvent) -> dict[str, Any]:
        payload = None
        if event.payload_json:
            try:
                payload = json.loads(event.payload_json)
            except json.JSONDecodeError:
                payload = event.payload_json

        return {
            "id": str(event.id),
            "seq_no": event.seq_no,
            "timestamp": self._iso(event.timestamp),
            "kind": event.step,
            "status": event.status,
            "level": event.level,
            "tone": trace_event_tone(status=event.status, level=event.level, step=event.step),
            "message": event.message,
            "payload": payload,
        }

    @staticmethod
    def _derive_applied_style(events: list[dict[str, Any]]) -> str | None:
        styles: list[str] = []
        for event in events:
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            style = payload.get("style")
            if not isinstance(style, str):
                continue
            normalized = style.strip()
            if not normalized:
                continue
            styles.append(normalized)

        unique_styles = sorted(set(styles))
        if not unique_styles:
            return None
        if len(unique_styles) == 1:
            return unique_styles[0]
        return "multiple"

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()
