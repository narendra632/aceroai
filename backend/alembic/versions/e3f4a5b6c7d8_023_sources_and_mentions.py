"""023 — where information comes from, and everything each source ever named

Two tables, and the second is the one that matters.

`sources` is the register of places the system reads: the exchange's announcement feeds, the
commentators, anything dropped into the inbox. Each carries a **trust tier**, because a number
in a company's own filing and a number in a video are different species and must never be
allowed to mix.

`mentions` records **every instrument every source names** — acted on or not, held or not,
dismissed or not.

⚠ **That last clause is the entire point of the table.** Judge a channel only on the ideas you
acted on and you are measuring your own filter, not the channel: the ideas you skipped are
missing from the denominator, so a source that named forty companies of which you looked at
three and one worked reads as 33% rather than 2.5%. Survivorship bias is not a subtle effect
here — it is the difference between a source looking excellent and looking useless, and the
only defence is to write down everything at the moment it is said, because it cannot be
reconstructed later.

⚠ **Trust tiers are load-bearing.** Tier 1 is a filing or a regulator; tier 2 is the press;
tier 3 is commentary. A proposal whose evidence is *only* tier 3 fails its sourcing gate — a
stock mentioned on a channel enters the research queue, it does not enter the portfolio.

`mentions` is append-only, `sources` is not: a feed can be switched off, and a source that
could never be deactivated would have to be deleted, which would orphan every mention that
ever cited it and quietly rewrite the attribution history.

⚠ **The mentions guard is narrowed, for the reason 021 had to narrow the claims guard.** What
must never change is *what was said*: which source item, about which instrument, with what
stance, in whose words. Whether that mention later became a proposal is **not a revision of
what was said** — it is a new fact, discovered later, about an utterance that has not moved.
Written as a whole-table guard, `became_proposal_id` could never be set at all and the column
would be decoration. This is the fourth time this trigger has caught its own author.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: What was said, and cannot be unsaid. ⚠ `became_proposal_id` is deliberately absent: it is
#: not part of the utterance, it is what happened afterwards.
_FROZEN = (
    "id",
    "source_item_id",
    "instrument_id",
    "stance",
    "claim_excerpt",
    "created_at",
)

_CONDITION = " OR ".join(f"OLD.{column} IS DISTINCT FROM NEW.{column}" for column in _FROZEN)

_GUARD = """
CREATE OR REPLACE FUNCTION mentions_utterance_is_frozen() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'a mention records what a source said: its instrument, stance and words cannot '
        'change once written. Record what it led to instead.'
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # A channel id, a feed URL, a filer id — whatever identifies it to its own system.
        sa.Column("handle", sa.Text(), nullable=False),
        # ⚠ 1 = filing or regulator · 2 = press · 3 = commentary. A proposal resting only on
        # tier 3 fails its sourcing gate: a stock named on a channel joins the research queue,
        # not the portfolio.
        sa.Column("trust_tier", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        # ⚠ Approved like a framework mapping, and for the same reason. Adding a source changes
        # what the system reads and therefore what it can be talked into; that is a decision,
        # not configuration.
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("last_polled_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "kind in ('RSS_EXCHANGE','RSS_NEWS','YOUTUBE','EDGAR','MACRO','USER_DROP')",
            name="sources_kind",
        ),
        sa.CheckConstraint("trust_tier between 1 and 3", name="sources_tier"),
        sa.UniqueConstraint("kind", "handle", name="sources_unique"),
    )

    op.create_table(
        "mentions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_item_id", sa.Uuid(), sa.ForeignKey("source_items.id"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("stance", sa.Text(), nullable=False),
        # The sentence that named it, capped — enough to check the reading, never the document.
        sa.Column("claim_excerpt", sa.Text()),
        # Set only if this mention actually led somewhere. ⚠ Usually NULL, and that is the
        # point: the rows with nothing here are the denominator.
        sa.Column("became_proposal_id", sa.Uuid(), sa.ForeignKey("proposals.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "stance in ('BULL','BEAR','NEUTRAL','MENTION_ONLY')", name="mentions_stance"
        ),
        sa.CheckConstraint("length(coalesce(claim_excerpt,'')) <= 1024", name="mentions_excerpt"),
        sa.UniqueConstraint("source_item_id", "instrument_id", name="mentions_unique"),
    )
    op.create_index("mentions_by_instrument", "mentions", ["instrument_id", "created_at"])

    # `source_items` gains a link to the source that produced it. Nullable because the
    # filings ingested before this migration have none, and inventing one would be a lie
    # about provenance in the one table whose whole purpose is provenance.
    op.add_column("source_items", sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id")))

    op.execute(_GUARD)
    # ⚠ DELETE is refused outright. A mention that can be removed after the fact is a mention
    # that never has to be counted — and the denominator is the only thing this table is for.
    op.execute(
        "CREATE TRIGGER mentions_no_delete BEFORE DELETE ON mentions "
        "FOR EACH ROW EXECUTE FUNCTION investments_append_only();"
    )
    op.execute(
        f"CREATE TRIGGER mentions_utterance_frozen BEFORE UPDATE ON mentions "
        f"FOR EACH ROW WHEN ({_CONDITION}) "
        f"EXECUTE FUNCTION mentions_utterance_is_frozen();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS mentions_utterance_frozen ON mentions;")
    op.execute("DROP TRIGGER IF EXISTS mentions_no_delete ON mentions;")
    op.execute("DROP FUNCTION IF EXISTS mentions_utterance_is_frozen();")
    op.drop_column("source_items", "source_id")
    op.drop_index("mentions_by_instrument", table_name="mentions")
    op.drop_table("mentions")
    op.drop_table("sources")
