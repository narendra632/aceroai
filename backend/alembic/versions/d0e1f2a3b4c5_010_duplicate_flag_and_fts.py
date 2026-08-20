"""010 a home for suspected duplicates, and a keyword index to search facts by word

Two changes, both serving the same failure: a fact the user asked to be remembered was
silently discarded, and nothing could have surfaced it.

**`possible_duplicate_of`** — the extractor used to delete any proposed fact whose
embedding sat within 0.12 of an existing one. Measured on the real pair that caused the
bug, `AI-901` and `AI-103` are 0.098 apart: two different certifications, indistinguishable
by distance. From now on such a fact is stored and *linked* to the one it might repeat, so
the ambiguity is visible on the Knowledge page instead of resolved by deletion.

**`profile_facts_fts`** — a GIN index over `to_tsvector('english', fact)`, which is what
lets recall search by word as well as by meaning. Measured: every fact about one person
falls in a 0.30-0.58 cosine band, so distance can tell you a fact is *about the user* but
not that it *answers the question*. Keyword matching is precise exactly where vectors are
vague.

The expression is immutable because the text-search config is named explicitly
(`'english'`, not `default`), so an expression index is sufficient and no generated column
is needed. Verified on this Postgres build before the migration was written.

The index is partial on the same predicate as `profile_facts_live_hnsw`: every recall query
filters `deleted_at IS NULL AND status = 'active'`, and an index whose WHERE clause does
not match the query's cannot drive the scan.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIVE = "deleted_at IS NULL AND status = 'active'"


def upgrade() -> None:
    op.add_column(
        "profile_facts",
        sa.Column("possible_duplicate_of", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "profile_facts_possible_duplicate_of_fkey",
        "profile_facts",
        "profile_facts",
        ["possible_duplicate_of"],
        ["id"],
    )
    op.execute(
        "CREATE INDEX profile_facts_fts ON profile_facts "
        f"USING gin (to_tsvector('english', fact)) WHERE {_LIVE}"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS profile_facts_fts")
    op.drop_constraint(
        "profile_facts_possible_duplicate_of_fkey", "profile_facts", type_="foreignkey"
    )
    op.drop_column("profile_facts", "possible_duplicate_of")
