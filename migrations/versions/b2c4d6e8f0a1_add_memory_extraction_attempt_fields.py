"""add memory extraction attempt fields

Revision ID: b2c4d6e8f0a1
Revises: 9f1c2d3e4a5b
Create Date: 2026-04-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b2c4d6e8f0a1"
down_revision: str | Sequence[str] | None = "9f1c2d3e4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "chat_messages", sa.Column("memory_process_attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("chat_messages", sa.Column("memory_last_attempt_at", sa.DateTime(), nullable=True))
    op.add_column("chat_messages", sa.Column("memory_last_error_code", sa.String(length=64), nullable=True))
    op.create_index(
        op.f("ix_chat_messages_memory_last_attempt_at"), "chat_messages", ["memory_last_attempt_at"], unique=False
    )
    op.create_index(
        op.f("ix_chat_messages_memory_last_error_code"), "chat_messages", ["memory_last_error_code"], unique=False
    )
    op.alter_column("chat_messages", "memory_process_attempts", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_chat_messages_memory_last_error_code"), table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_memory_last_attempt_at"), table_name="chat_messages")
    op.drop_column("chat_messages", "memory_last_error_code")
    op.drop_column("chat_messages", "memory_last_attempt_at")
    op.drop_column("chat_messages", "memory_process_attempts")
