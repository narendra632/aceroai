"""012 notifications and briefings become deletable

`notifications` and `generated_reviews` were the only user-facing records in the application
with no way to remove them. Every other one — tasks, journal entries, chat sessions, profile
facts — has been soft-deletable since migration 004, and `ui-standards` states the rule as a
requirement. These two were simply left out.

Same shape as 004: nullable `deleted_at`, no backfill, existing rows stay visible.

Two readers of `notifications` must NOT filter this column, which is the opposite of every
other soft-deleted table and is the reason this migration has a long docstring:

- `_already_said()` asks whether a nudge has already been raised for a situation. Filter
  deleted rows and dismissing "3 tasks are overdue" would make the next hourly run treat it as
  news and push it again — delete would silently mean "remind me within the hour".
- `_pushed_today()` counts what was delivered. A count of deliveries is a count of
  deliveries, not of surviving receipts.

The rule: **readers that list rows filter deleted; readers that ask what already happened do
not.** Both exceptions are pinned by tests in `test_notifications.py`.

`generated_reviews` gains its first index. It has been queried by
`(user_id, period_start DESC)` since the briefings tab shipped and has been served by a
sequential scan; adding the column is the moment to fix that.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-24 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("notifications", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("generated_reviews", sa.Column("deleted_at", sa.DateTime(timezone=True)))

    # The unread badge is read on every page load and now filters both predicates. A partial
    # index can only serve a query whose WHERE clause implies the index's own — so both
    # conditions belong in it, or Postgres falls back to the table. (Migration 010 records
    # the same lesson about the live-facts index.)
    op.drop_index("notifications_unread", table_name="notifications")
    op.create_index(
        "notifications_unread",
        "notifications",
        ["user_id"],
        postgresql_where=sa.text("read_at IS NULL AND deleted_at IS NULL"),
    )

    # `notifications_recent` is deliberately left alone. It is an ordering index rather than
    # a partial one, so it still serves the listing query; the deleted rows it now includes
    # are a handful filtered after the fact, which is cheaper than maintaining a second index.

    # `generated_reviews` had no index at all beyond its primary key. This is the shape the
    # briefings tab actually reads it in.
    op.create_index(
        "generated_reviews_live",
        "generated_reviews",
        ["user_id", sa.text("period_start DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema.

    As in migration 004: rows soft-deleted while this migration was applied become visible
    again, because the only record of their deletion is the column being dropped. That is
    stated rather than prevented — the alternative is a downgrade that destroys data.
    """
    op.drop_index("generated_reviews_live", table_name="generated_reviews")
    op.drop_column("generated_reviews", "deleted_at")

    op.drop_index("notifications_unread", table_name="notifications")
    op.create_index(
        "notifications_unread",
        "notifications",
        ["user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.drop_column("notifications", "deleted_at")
