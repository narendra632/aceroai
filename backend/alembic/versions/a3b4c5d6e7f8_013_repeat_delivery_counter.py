"""013 a notification can be delivered more than once

Until now a notification was delivered at most once, so "was it delivered" and "how many
times" were the same question and `pushed_at` answered both. The overdue nudge now reminds
the user every two hours until they act, against a single record per day rather than one
record per reminder — so the two questions come apart and the table needs to answer both.

`pushed_at` changes meaning from *when it was delivered* to *when it was **last**
delivered*. No reader breaks: `pushed_today` filters on it being non-null and within today,
which stays true, and the panel shows it as "last reminded". The meaning is restated in the
model docstring and in the `notifications` spec so the change is not carried only by this
file.

**Why `DEFAULT 0` and a backfill rather than `DEFAULT 1` and none.**

`DEFAULT 1` would have needed no backfill, because every existing delivered row was
delivered exactly once. But a DDL default applies to future inserts too, and a notification
is INSERTed *before* delivery is attempted — deliberately, so the record survives a failed
send. A row that is written and then fails to reach any device would carry a count of 1
while having interrupted the user zero times, and rows that never reach a device are
common: quiet hours, no subscription, a phone that has uninstalled the browser.

So the counter starts at zero and is incremented by the code that actually delivers.
Every value in the column is then true, rather than true for the rows that happen to
succeed. The one-time backfill states the historical fact separately: rows with a non-null
`pushed_at` were delivered, once.

**No new index.** Finding today's live record for a `(kind, tag)` pair is served well
enough by `notifications_recent` on `(user_id, created_at DESC)`; the residual filter runs
over a single user's notifications for one day, which is single digits. An index on
`(kind, tag)` would cost writes on every notification to save nothing measurable.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-27 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notifications",
        sa.Column("push_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        sa.text(
            """
            COMMENT ON COLUMN notifications.push_count IS
            'How many times this record was delivered to at least one device. Counts '
            'deliveries, not records: one record reminded about seven times has '
            'interrupted the user seven times.'
            """
        )
    )
    # The historical fact, stated once. Before this migration a record could be delivered
    # at most once, so a non-null pushed_at means exactly one delivery.
    op.execute(sa.text("UPDATE notifications SET push_count = 1 WHERE pushed_at IS NOT NULL"))


def downgrade() -> None:
    """Downgrade schema.

    Dropping the column loses the repeat counts and nothing else. `pushed_at` silently
    reverts to meaning "when it was delivered", which is accurate again the moment nothing
    delivers a record twice.
    """
    op.drop_column("notifications", "push_count")
