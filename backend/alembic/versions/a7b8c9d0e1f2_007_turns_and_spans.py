"""007 traces: what each turn cost and where its time went

`core.telemetry.Timeline` already produced a trace — ordered named stages with durations,
plus provider usage — and then formatted it into a log line and threw it away. Nothing was
queryable, nothing aggregated, and cost was never computed at all.

Two tables, with column names mapped onto OpenTelemetry's GenAI semantic conventions
(gen_ai.request.model, gen_ai.usage.input_tokens, ...) so exporting to a collector later is
a formatting change rather than a redesign:

- `turns` — one row per model call, INCLUDING the background ones. A user message triggers
  up to four provider calls (embed for recall, the reply, the fact extractor, embed for new
  facts) and only the reply produced a `messages` row. `kind` is what makes the other three
  attributable instead of invisible.
- `spans` — one row per stage of a turn: memory_recall, build_context, llm_round1,
  tool:create_task, persist_assistant. This is what draws the per-turn waterfall.

Deliberately absent: prompt and response TEXT. `messages` already holds the content;
duplicating it here would double both the disk footprint and the blast radius of a leak.
Traces record shape, counts and durations only.

`cost_usd` is stored, not computed at read time, alongside the `pricing_version` that
produced it — so a later price change cannot silently rewrite last month's spend.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-18 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # Background work has no conversation; a job has neither.
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        # What this call was FOR. Without it, background spend cannot be told apart from
        # the reply the user actually saw.
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("effort", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # The number the user actually feels: request in -> first word out.
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("rounds", sa.SmallInteger(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        # Billed at the output rate but separately controllable, so kept apart.
        sa.Column("tokens_thinking", sa.Integer(), nullable=True),
        sa.Column("tokens_cached", sa.Integer(), nullable=True),
        # NULL means "no price known for this model" — never 0, which is a lie that
        # silently understates a total.
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("pricing_version", sa.Text(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind in ('chat','memory_extract','embed','job')", name="turns_kind"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_turns_started_at", "turns", ["started_at"])
    op.create_index("ix_turns_user_started", "turns", ["user_id", "started_at"])

    op.create_table(
        "spans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # Stages are ordered; the waterfall is meaningless otherwise.
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # Counts and identifiers only — never message text.
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Spans are always fetched for one turn, and pruned by their turn's age.
    op.create_index("ix_spans_turn", "spans", ["turn_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_spans_turn", table_name="spans")
    op.drop_table("spans")
    op.drop_index("ix_turns_user_started", table_name="turns")
    op.drop_index("ix_turns_started_at", table_name="turns")
    op.drop_table("turns")
