"""add provider runtime state.

Revision ID: 67a6d3ac58d2
Revises: c1d1b5fb56d4
Create Date: 2026-04-14 11:24:09.279069

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "67a6d3ac58d2"  # noqa: COP003
down_revision: str | Sequence[str] | None = "c1d1b5fb56d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:  # noqa: COP007
    op.create_table(
        "provider_runtime_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=128), nullable=False),
        sa.Column("current_model_name", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_runtime_states_provider_name"),
        "provider_runtime_states",
        ["provider_name"],
        unique=True,
    )
    op.create_index(
        op.f("ix_provider_runtime_states_updated_at"),
        "provider_runtime_states",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_provider_runtime_states_updated_at"), table_name="provider_runtime_states")
    op.drop_index(op.f("ix_provider_runtime_states_provider_name"), table_name="provider_runtime_states")
    op.drop_table("provider_runtime_states")
