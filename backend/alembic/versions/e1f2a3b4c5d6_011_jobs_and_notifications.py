"""011 recurring work that records itself, and a durable place for what the user is told

Four new tables and one removal, all serving one shift: Acero stops being purely reactive.

**`job_runs`** is the important one. The scheduler is only a ticker — this table is the
source of truth about whether a job has run. Every occurrence resolves to a key
(`day_end_summary@2026-08-24T21:00:00+05:30`) that is unique here, so a repeated tick, a
restarted container and a manual trigger all converge on exactly one execution. Without it,
a deploy at 20:58 would kill the 21:00 run of an in-memory scheduler and report nothing.

**`notifications`** exists because a push notification is not a record. It is swiped away,
refused permission, or delivered to a laptop that is closed. The row is written *before*
delivery is attempted, so what the system had to say survives every one of those.

**`push_subscriptions`** holds what the browser's push service handed us: an endpoint plus
two keys. `endpoint` is unique because re-subscribing the same browser must update the row
rather than accumulate dead ones — and dead ones are real, since a push service returns 410
when a browser is uninstalled or its storage cleared.

**`user_job_prefs`** is deliberately **sparse**: no row means "use the job's declared
default". That is what makes adding a future job a code change with no migration behind it,
which was an explicit requirement of this change rather than a happy accident.

**`users.telegram_chat_id` is dropped** — the Telegram channel is retired. Note what is NOT
dropped: `chat_sessions.channel` keeps its `('web','telegram')` CHECK. Those rows are real
conversations, and rewriting them to 'web' would make the record lie about where they
happened. The constraint stays permissive on purpose.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- job_runs -------------------------------------------------------------------
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_name", sa.Text(), nullable=False),
        # The scheduled instant this run satisfies, as an ISO string in local time. Text
        # rather than timestamptz so the key is exactly what the runner computed — two
        # representations of "the same instant" must never produce two rows.
        sa.Column("occurrence_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_type", sa.Text()),
        # Counts and identifiers only — never message text, same rule as `spans.meta`.
        sa.Column("detail", JSONB()),
        sa.UniqueConstraint("job_name", "occurrence_key", name="job_runs_occurrence"),
        sa.CheckConstraint(
            "status in ('ok','silent','failed','skipped_budget','skipped_disabled','missed')",
            name="job_runs_status",
        ),
    )
    # Answers "when did this job last run", which is what the Settings screen shows.
    op.create_index("job_runs_recent", "job_runs", ["job_name", sa.text("started_at DESC")])

    # --- notifications --------------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        # Where selecting this notification should take the user, as an in-app route.
        sa.Column("url", sa.Text()),
        # Groups notifications that supersede one another on the device.
        sa.Column("tag", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        # NULL means never delivered to a device — refused permission, quiet hours, a
        # failed send, or no subscription. The notification is no less real for it.
        sa.Column("pushed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "notifications_recent", "notifications", ["user_id", sa.text("created_at DESC")]
    )
    # Partial: the unread count is read on every page load, and the unread set is the
    # small tail of a table that only grows.
    op.create_index(
        "notifications_unread",
        "notifications",
        ["user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )

    # --- push_subscriptions ---------------------------------------------------------
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        # Unique so re-subscribing the same browser updates rather than duplicates.
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        # Only so the user can tell two devices apart in Settings.
        sa.Column("user_agent", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_ok_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index("push_subscriptions_user", "push_subscriptions", ["user_id"])

    # --- user_job_prefs -------------------------------------------------------------
    # Sparse by design: absence means "the job's declared default". A new job therefore
    # needs no migration, no backfill, and no default row per user.
    op.create_table(
        "user_job_prefs",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("job_name", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # --- users ----------------------------------------------------------------------
    # Local hours. NULL on either means quiet hours are off for this user.
    op.add_column("users", sa.Column("quiet_hours_start", sa.SmallInteger()))
    op.add_column("users", sa.Column("quiet_hours_end", sa.SmallInteger()))
    op.add_column("users", sa.Column("daily_push_cap", sa.SmallInteger()))

    # Telegram is retired. Nothing reads this column.
    op.drop_column("users", "telegram_chat_id")


def downgrade() -> None:
    # Restored nullable and unique exactly as migration 001 created it, so the downgrade
    # is genuinely reversible. The chat ids themselves are gone — a dropped column takes
    # its data with it, and a downgrade cannot invent it back. Re-link with /start.
    op.add_column("users", sa.Column("telegram_chat_id", sa.BigInteger(), unique=True))

    op.drop_column("users", "daily_push_cap")
    op.drop_column("users", "quiet_hours_end")
    op.drop_column("users", "quiet_hours_start")

    op.drop_table("user_job_prefs")
    op.drop_index("push_subscriptions_user", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_index("notifications_unread", table_name="notifications")
    op.drop_index("notifications_recent", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("job_runs_recent", table_name="job_runs")
    op.drop_table("job_runs")
