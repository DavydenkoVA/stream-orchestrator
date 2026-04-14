from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal
from app.models.trace_event import TraceEvent
from app.models.trace_run import TraceRun

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
                status="running",
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
