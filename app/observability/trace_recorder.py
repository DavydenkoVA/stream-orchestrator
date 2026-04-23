from __future__ import annotations
import datetime
import json
import typing

from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal
from app.models.trace_event import TraceEvent
from app.models.trace_run import TraceRun
from app.observability.trace_status import (
    TRACE_RUN_STATUS_DEGRADED,
    TRACE_RUN_STATUS_RUNNING,
    TRACE_RUN_STATUS_SUCCESS,
)


SENSITIVE_MARKERS: typing.Final = {
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


@typing.final
class TraceRecorder:
    def __init__(self, *, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or SessionLocal

    @classmethod
    def from_db_session(cls, database_session: Session) -> TraceRecorder:  # noqa: COP009
        return cls(
            session_factory=sessionmaker(
                bind=database_session.get_bind(), autoflush=False, autocommit=False, future=True
            )
        )

    def start_run(  # noqa: COP006
        self,
        *,
        trace_id: str,
        request_id: str,
        route: str,  # noqa: COP006
        stream_id: str | None,  # noqa: COP006
    ) -> int:
        with self._session_factory() as database_session:
            trace_run_record = TraceRun(
                trace_id=trace_id,
                request_id=request_id,
                route=route,
                stream_id=stream_id,
                status=TRACE_RUN_STATUS_RUNNING,
            )
            database_session.add(trace_run_record)
            database_session.commit()
            database_session.refresh(trace_run_record)
            return trace_run_record.id

    def append_event(  # noqa: PLR0913, COP009
        self,
        *,
        trace_run_id: int,
        seq_no: int,  # noqa: COP006
        step: str,  # noqa: COP006
        status: str,  # noqa: COP006
        level: str,  # noqa: COP006
        message: str,  # noqa: COP006
        payload: dict[str, typing.Any] | None = None,  # noqa: COP006
    ) -> None:
        with self._session_factory() as database_session:
            sanitized_payload = make_sanitized_trace_payload(payload)
            trace_event_record = TraceEvent(
                trace_run_id=trace_run_id,
                seq_no=seq_no,
                timestamp=datetime.datetime.now(datetime.UTC),
                step=step,
                status=status,
                level=level,
                message=message,
                payload_json=json.dumps(sanitized_payload, ensure_ascii=False) if sanitized_payload else None,
            )
            database_session.add(trace_event_record)
            database_session.commit()

    def finish_run(  # noqa: COP009
        self,
        *,
        trace_run_id: int,
        status: str,  # noqa: COP006
        error_code: str | None = None,
        summary: str | None = None,  # noqa: COP006
    ) -> None:
        with self._session_factory() as database_session:
            trace_run_record = database_session.get(TraceRun, trace_run_id)
            if trace_run_record is None:
                return
            trace_run_record.status = status
            trace_run_record.error_code = error_code
            trace_run_record.summary = summary
            trace_run_record.finished_at = datetime.datetime.now(datetime.UTC)
            database_session.commit()

    def finish_run_success(  # noqa: COP009
        self,
        *,
        trace_run_id: int,
        summary: str | None = None,  # noqa: COP006
    ) -> None:
        with self._session_factory() as database_session:
            trace_run_record = database_session.get(TraceRun, trace_run_id)
            if trace_run_record is None:
                return

            trace_events = list(
                database_session.query(TraceEvent)
                .filter(TraceEvent.trace_run_id == trace_run_id)
                .order_by(TraceEvent.seq_no.asc(), TraceEvent.id.asc())
                .all()
            )
            derived_status = self._derive_success_status(trace_run_record=trace_run_record, trace_events=trace_events)

            trace_run_record.status = derived_status
            if derived_status == TRACE_RUN_STATUS_DEGRADED and not trace_run_record.error_code:
                trace_run_record.error_code = "llm_error"
            trace_run_record.summary = summary
            trace_run_record.finished_at = datetime.datetime.now(datetime.UTC)
            database_session.commit()

    @staticmethod
    def _derive_success_status(*, trace_run_record: TraceRun, trace_events: list[TraceEvent]) -> str:  # noqa: COP009
        is_llm_dependent_route = trace_run_record.route in {"/events/chat_reply", "/events/dynamic_prompt"}

        has_llm_success_event = any(
            one_event.step in {"llm.generate.success", "dynamic_prompt.llm.success"} for one_event in trace_events
        )
        has_llm_failure_event = any(
            one_event.step in {"llm.model.failed", "llm.generate.failed", "dynamic_prompt.llm.failed"}
            for one_event in trace_events
        )
        has_llm_related_event = any(
            one_event.step.startswith("llm.") or one_event.step.startswith("dynamic_prompt.llm.")
            for one_event in trace_events
        )

        if (is_llm_dependent_route or has_llm_related_event) and has_llm_failure_event and not has_llm_success_event:
            return TRACE_RUN_STATUS_DEGRADED
        return TRACE_RUN_STATUS_SUCCESS


def make_sanitized_trace_payload(
    payload: dict[str, typing.Any] | None,  # noqa: COP006
) -> dict[str, typing.Any] | None:
    if payload is None:
        return None

    def clean_payload_value(payload_value: typing.Any, parent_key_name: str = "") -> typing.Any:  # noqa: ANN401, COP009
        if isinstance(payload_value, dict):
            cleaned_payload: dict[str, typing.Any] = {}
            for one_key, one_item in payload_value.items():
                key_lowercase = str(one_key).lower()
                if key_lowercase in SENSITIVE_MARKERS:
                    continue
                if any(one_marker in key_lowercase for one_marker in SENSITIVE_MARKERS):
                    continue
                cleaned_payload[one_key] = clean_payload_value(one_item, parent_key_name=key_lowercase)
            return cleaned_payload
        if isinstance(payload_value, list):
            return [clean_payload_value(one_value, parent_key_name=parent_key_name) for one_value in payload_value]
        if isinstance(payload_value, str) and parent_key_name.endswith("prompt"):
            return f"[redacted_prompt length={len(payload_value)}]"
        return payload_value

    return typing.cast("dict[str, typing.Any] | None", clean_payload_value(payload))


def sanitize_payload(payload: dict[str, typing.Any] | None) -> dict[str, typing.Any] | None:  # noqa: COP009, COP006
    return make_sanitized_trace_payload(payload)
