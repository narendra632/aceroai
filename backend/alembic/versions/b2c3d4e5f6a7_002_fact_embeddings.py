"""002 fact embeddings

Adds a pgvector embedding column + HNSW index to profile_facts so facts can be
recalled by semantic similarity. The `vector` extension is already enabled by 001.

Revision ID: b2c3d4e5f6a7
Revises: f6eaae243cfc
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "f6eaae243cfc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 768 dims matches settings.embed_dim (gemini-embedding-001 @ 768).
    op.execute("ALTER TABLE profile_facts ADD COLUMN embedding vector(768)")
    op.execute(
        "CREATE INDEX profile_facts_embedding_hnsw "
        "ON profile_facts USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS profile_facts_embedding_hnsw")
    op.execute("ALTER TABLE profile_facts DROP COLUMN embedding")
