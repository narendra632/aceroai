"""005 memory lifecycle: facts become forgettable and editable

`profile_facts` gains the two columns a user-facing memory needs:

- `deleted_at` — forgetting a fact is reversible, exactly as migration 004 made deleting a
  task reversible. Readers must filter `deleted_at IS NULL`; that filter lives in
  `services/memory.py` so no caller can forget it.
- `updated_at` — a record the user can edit needs to say when it last changed.

The partial index covers the rows every read actually asks for: a user's live, active
facts. Note it must match the *query* shape — recall filters `status = 'active'` AND
`deleted_at IS NULL`, so both predicates belong in the index or Postgres cannot use it.

The HNSW vector index from migration 002 is deliberately left alone. Postgres can combine
it with the partial index above; rebuilding it as a partial index would mean dropping and
recreating every vector, which is expensive and buys nothing at this size.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "profile_facts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Existing rows get their creation time rather than NULL: a fact that has never been
    # edited was last "changed" when it was written, and a NULL here would force every
    # reader to special-case it.
    op.add_column(
        "profile_facts",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute("UPDATE profile_facts SET updated_at = created_at")

    op.create_index(
        "ix_profile_facts_user_live",
        "profile_facts",
        ["user_id"],
        postgresql_where=sa.text("deleted_at IS NULL AND status = 'active'"),
    )


def downgrade() -> None:
    """Downgrade schema.

    Note: facts forgotten while this migration was applied become visible again on
    downgrade, because the only record of the forgetting is the column being dropped.
    """
    op.drop_index("ix_profile_facts_user_live", table_name="profile_facts")
    op.drop_column("profile_facts", "updated_at")
    op.drop_column("profile_facts", "deleted_at")
