"""003 user model preferences

Adds the per-user provider/model selection driven from the Settings screen. All three
columns are nullable: NULL means "use the server's configured default", so existing
rows keep behaving exactly as before.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("llm_provider", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("model_chat", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("model_deep", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "model_deep")
    op.drop_column("users", "model_chat")
    op.drop_column("users", "llm_provider")
