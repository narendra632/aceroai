"""004 soft delete for tasks, journal entries and chat sessions

Deleting is made reversible: `DELETE` now stamps `deleted_at` instead of removing the
row, and Undo clears it. The column is nullable and existing rows keep NULL, so every
current record stays visible with no backfill.

Readers must filter `deleted_at IS NULL`. That filter lives in the `services/` query
builders — the single layer shared by the REST API, the assistant's tools, and the
composer's task block — so no caller can forget it.

Partial indexes cover only the live rows, which is what every read asks for; deleted
rows are never listed, only fetched by id during an undo.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("tasks", "journal_entries", "chat_sessions")


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        # Partial index: reads always want the live rows, so only those are indexed.
        op.create_index(
            f"ix_{table}_user_active",
            table,
            ["user_id"],
            postgresql_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    """Downgrade schema.

    Note: rows soft-deleted while this migration was applied become visible again on
    downgrade, because the only record of their deletion is the column being dropped.
    """
    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_user_active", table_name=table)
        op.drop_column(table, "deleted_at")
