"""009 monthly spend cap

Observability could report cost but not stop it. This adds a per-user monthly ceiling,
checked before each message.

NULL means no limit, so every existing account behaves exactly as it did before.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("monthly_budget_usd", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "monthly_budget_usd")
