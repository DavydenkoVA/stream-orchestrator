"""add memory pipeline fields

Revision ID: 528ab8411a47
Revises: 
Create Date: 2026-04-04 03:10:55.698023

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "528ab8411a47"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "is_memory_processed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        op.f("ix_chat_messages_is_memory_processed"),
        "chat_messages",
        ["is_memory_processed"],
        unique=False,
    )

    op.add_column(
        "user_memory_items",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("'1970-01-01 00:00:00'"),
        ),
    )
    op.create_index(
        op.f("ix_user_memory_items_updated_at"),
        "user_memory_items",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_memory_items_updated_at"), table_name="user_memory_items")
    op.drop_column("user_memory_items", "updated_at")

    op.drop_index(op.f("ix_chat_messages_is_memory_processed"), table_name="chat_messages")
    op.drop_column("chat_messages", "is_memory_processed")