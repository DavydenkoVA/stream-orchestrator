from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal
from app.models.trace_event import TraceEvent
from app.models.trace_run import TraceRun
from app.observability.trace_status import (
    TRACE_RUN_STATUS_DEGRADED,
    TRACE_RUN_STATUS_RUNNING,
    TRACE_RUN_STATUS_SUCCESS,
)

SENSITIVE_MARKERS = {
    "api_key",
    "authorization",
    "secret",
    "password",
    "token",
    "traceback",
    "stacktrace",
    "system_prompt",
    "user_prompt",
    "prompt",
}


class TraceRecorder:
    def __init__(self, *, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or SessionLocal

    @classmethod
    def from_db_session(cls, db: Session) -> "TraceRecorder":
        bind = db.get_bind()
        session_factory = sessionmaker(bind=bind, autoflush=False, autocommit=False, future=True)
        return cls(session_factory=session_factory)

    def start_run(
        self,
        *,
        trace_id: str,
        request_id: str,
        route: str,
        stream_id: str | None,
    ) -> int:
        with self._session_factory() as session:
            run = TraceRun(
                trace_id=trace_id,
                request_id=request_id,
                route=route,
                stream_id=stream_id,
                status=TRACE_RUN_STATUS_RUNNING,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run.id

    def append_event(
        self,
        *,
        trace_run_id: int,
        seq_no: int,
        step: str,
        status: str,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._session_factory() as session:
            safe_payload = sanitize_payload(payload)
            event = TraceEvent(
                trace_run_id=trace_run_id,
                seq_no=seq_no,
                timestamp=datetime.now(UTC),
                step=step,
                status=status,
                level=level,
                message=message,
                payload_json=json.dumps(safe_payload, ensure_ascii=False) if safe_payload else None,
            )
            session.add(event)
            session.commit()

    def finish_run(
        self,
        *,
        trace_run_id: int,
        status: str,
        error_code: str | None = None,
        summary: str | None = None,
    ) -> None:
        with self._session_factory() as session:
            run = session.get(TraceRun, trace_run_id)
            if run is None:
                return
            run.status = status
            run.error_code = error_code
            run.summary = summary
            run.finished_at = datetime.now(UTC)
            session.commit()

    def finish_run_success(
        self,
        *,
        trace_run_id: int,
        summary: str | None = None,
    ) -> None:
        with self._session_factory() as session:
            run = session.get(TraceRun, trace_run_id)
            if run is None:
                return

            events = list(
                session.query(TraceEvent)
                .filter(TraceEvent.trace_run_id == trace_run_id)
                .order_by(TraceEvent.seq_no.asc(), TraceEvent.id.asc())
                .all()
            )
            derived_status = self._derive_success_status(run=run, events=events)

            run.status = derived_status
            if derived_status == TRACE_RUN_STATUS_DEGRADED and not run.error_code:
                run.error_code = "llm_error"
            run.summary = summary
            run.finished_at = datetime.now(UTC)
            session.commit()

    @staticmethod
    def _derive_success_status(*, run: TraceRun, events: list[TraceEvent]) -> str:
        llm_dependent_route = run.route in {"/events/chat_reply", "/events/dynamic_prompt"}

        llm_success = any(
            event.step in {"llm.generate.success", "dynamic_prompt.llm.success"}
            for event in events
        )
        llm_failure = any(
            event.step in {"llm.model.failed", "llm.generate.failed", "dynamic_prompt.llm.failed"}
            for event in events
        )
        llm_was_involved = any(
            event.step.startswith("llm.") or event.step.startswith("dynamic_prompt.llm.")
            for event in events
        )

        if (llm_dependent_route or llm_was_involved) and llm_failure and not llm_success:
            return TRACE_RUN_STATUS_DEGRADED
        return TRACE_RUN_STATUS_SUCCESS


def sanitize_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None

    def _clean(value: Any, parent_key: str = "") -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                key_lower = str(key).lower()
                if key_lower in SENSITIVE_MARKERS or any(marker in key_lower for marker in SENSITIVE_MARKERS):
                    continue
                cleaned[key] = _clean(item, parent_key=key_lower)
            return cleaned
        if isinstance(value, list):
            return [_clean(v, parent_key=parent_key) for v in value]
        if isinstance(value, str) and parent_key.endswith("prompt"):
            return f"[redacted_prompt length={len(value)}]"
        return value

    return _clean(payload)
