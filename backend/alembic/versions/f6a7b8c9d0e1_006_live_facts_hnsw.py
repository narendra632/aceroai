"""006 an HNSW index the vector queries can actually use

Migration 002 added `profile_facts_embedding_hnsw` over the whole table. Measured, nothing
ever used it: every vector query in this app also filters `status = 'active'` and (since
005) `deleted_at IS NULL`, and pgvector can only let HNSW drive a scan when the index
covers the query's predicates. The planner fell back to a sequential scan plus a sort, and
at small row counts that was correct and free — so the index sat there costing write time
and disk for no read benefit.

It stops being free as the memory grows. The knowledge graph asks each fact for its
nearest neighbours, which without an index is an N x N comparison of 768-dimensional
vectors. Measured on 800 synthetic facts:

    without a matching index   5619 ms
    with this partial index     170 ms      (33x)

Recall benefits too — it has the same predicate shape, and it runs on every single message.

The old full index is dropped rather than kept alongside: no query in the app can use it,
and a second HNSW index on the same column doubles the cost of every insert.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIVE = "deleted_at IS NULL AND status = 'active'"


def upgrade() -> None:
    """Upgrade schema."""
    # The WHERE clause must match what the queries filter on, or the planner cannot use it.
    op.execute(
        "CREATE INDEX profile_facts_live_hnsw ON profile_facts "
        f"USING hnsw (embedding vector_cosine_ops) WHERE {_LIVE}"
    )
    op.execute("DROP INDEX IF EXISTS profile_facts_embedding_hnsw")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "CREATE INDEX profile_facts_embedding_hnsw "
        "ON profile_facts USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("DROP INDEX IF EXISTS profile_facts_live_hnsw")
