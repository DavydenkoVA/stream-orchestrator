"""add trace tables.

Revision ID: 9f1c2d3e4a5b
Revises: 67a6d3ac58d2
Create Date: 2026-04-14 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9f1c2d3e4a5b"  # noqa: COP003
down_revision: str | Sequence[str] | None = "67a6d3ac58d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:  # noqa: COP007
    op.create_table(
        "trace_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("route", sa.String(length=255), nullable=False),
        sa.Column("stream_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id"),
    )
    op.create_index(op.f("ix_trace_runs_trace_id"), "trace_runs", ["trace_id"], unique=True)
    op.create_index(op.f("ix_trace_runs_request_id"), "trace_runs", ["request_id"], unique=False)
    op.create_index(op.f("ix_trace_runs_route"), "trace_runs", ["route"], unique=False)
    op.create_index(op.f("ix_trace_runs_stream_id"), "trace_runs", ["stream_id"], unique=False)
    op.create_index(op.f("ix_trace_runs_status"), "trace_runs", ["status"], unique=False)
    op.create_index(op.f("ix_trace_runs_started_at"), "trace_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_trace_runs_finished_at"), "trace_runs", ["finished_at"], unique=False)

    op.create_table(
        "trace_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trace_run_id", sa.Integer(), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("step", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["trace_run_id"], ["trace_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trace_events_trace_run_id"), "trace_events", ["trace_run_id"], unique=False)
    op.create_index(op.f("ix_trace_events_timestamp"), "trace_events", ["timestamp"], unique=False)
    op.create_index(op.f("ix_trace_events_step"), "trace_events", ["step"], unique=False)
    op.create_index(op.f("ix_trace_events_status"), "trace_events", ["status"], unique=False)
    op.create_index(op.f("ix_trace_events_level"), "trace_events", ["level"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_trace_events_level"), table_name="trace_events")
    op.drop_index(op.f("ix_trace_events_status"), table_name="trace_events")
    op.drop_index(op.f("ix_trace_events_step"), table_name="trace_events")
    op.drop_index(op.f("ix_trace_events_timestamp"), table_name="trace_events")
    op.drop_index(op.f("ix_trace_events_trace_run_id"), table_name="trace_events")
    op.drop_table("trace_events")

    op.drop_index(op.f("ix_trace_runs_finished_at"), table_name="trace_runs")
    op.drop_index(op.f("ix_trace_runs_started_at"), table_name="trace_runs")
    op.drop_index(op.f("ix_trace_runs_status"), table_name="trace_runs")
    op.drop_index(op.f("ix_trace_runs_stream_id"), table_name="trace_runs")
    op.drop_index(op.f("ix_trace_runs_route"), table_name="trace_runs")
    op.drop_index(op.f("ix_trace_runs_request_id"), table_name="trace_runs")
    op.drop_index(op.f("ix_trace_runs_trace_id"), table_name="trace_runs")
    op.drop_table("trace_runs")
