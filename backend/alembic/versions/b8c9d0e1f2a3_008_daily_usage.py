"""008 daily_usage — the rollup that outlives the traces behind it

`turns` and `spans` are written on every model call. On a host with 10 GB of disk that is
unbounded growth, so both are pruned (see `services/retention.py`). This table is what
survives: one small row per day per model, kept indefinitely, so "what did I spend in
March" stays answerable after the individual calls are gone.

A day is bucketed in the app's configured timezone, not UTC — that is the day the Insights
page draws, and rolling up in UTC would shift every bucket by the offset.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        # NOT NULL with unknowns coalesced to a literal: Postgres treats NULLs as distinct
        # in a unique constraint, so a nullable key column would let the same day be
        # inserted again on every sweep instead of updated.
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("unpriced", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("tokens_thinking", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        # The upsert target: re-running a sweep updates the day rather than duplicating it.
        sa.UniqueConstraint("user_id", "day", "kind", "provider", "model", name="daily_usage_key"),
    )
    op.create_index("ix_daily_usage_user_day", "daily_usage", ["user_id", "day"])


def downgrade() -> None:
    op.drop_index("ix_daily_usage_user_day", table_name="daily_usage")
    op.drop_table("daily_usage")
