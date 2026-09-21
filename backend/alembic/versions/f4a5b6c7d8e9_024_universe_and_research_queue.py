"""024 — every listed company, and the queue of ones worth a look

Two tables, and together they are what turns the module from a bookkeeper into a research
assistant.

`listed_companies` is the exchange's own equity list — 2,595 companies, symbol and legal name.
It is the **vocabulary** the reader recognises names with.

⚠ **Why it has to exist.** Until now a company was only recognised if it was already held or
watched, so a channel naming something new produced nothing at all — the system could say
hold, trim or sell, and could never say *look at this*. The obvious alternative is to ask a
model which companies were discussed, and a model that can produce names can produce ones
that do not exist. That would put fictional companies into the very table the source
attribution measure counts, where an invented mention is indistinguishable from a real one.
With the exchange's list as the vocabulary, recognising a company never heard of is exactly
as deterministic as recognising one already owned.

`candidates` is the research queue: a company something named, which is not held and not
watched, waiting to be looked at.

⚠ **`mentions` has to change with them, and the change is a correction.** 023 wrote
`instrument_id NOT NULL`, which quietly assumed every company anyone names is one the
portfolio already follows — the same assumption that made discovery impossible. A mention is
about a *company*; sometimes that company is tracked and sometimes it is merely listed. So
the column becomes nullable, `listed_company_id` joins it, and a CHECK insists on exactly one
of the two. Both are set at insert, so the append-only guarantee is untouched — and the
trigger's frozen-column list grows to cover the new one, because a column outside that list
would be silently editable after the fact.

⚠ **A candidate is not an instrument in the portfolio sense.** It has an identity so it can be
referenced, and it is deliberately NOT priced daily — pricing every name ever mentioned would
spend the API allowance and the disk budget on companies nobody has decided to care about. It
costs nothing until it earns attention, and promoting it is what starts the meter.

⚠ **`dismissed_reason` is required when a candidate is dropped**, for the same reason a
decision requires one: it is the data that eventually reveals what kinds of idea keep being
refused, which is the only way anyone learns anything about their own filter. A queue that
could be cleared silently would throw that away every time it was tidied.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: What a mention says, and cannot unsay. ⚠ `became_proposal_id` stays out: it is not part of
#: the utterance, it is what happened afterwards.
_FROZEN = (
    "id",
    "source_item_id",
    "instrument_id",
    "listed_company_id",
    "stance",
    "claim_excerpt",
    "created_at",
)

#: The same list as 023 knew it, so the downgrade restores that trigger rather than a mutant.
_FROZEN_023 = tuple(c for c in _FROZEN if c != "listed_company_id")


def _condition(columns: Sequence[str]) -> str:
    return " OR ".join(f"OLD.{column} IS DISTINCT FROM NEW.{column}" for column in columns)


_FROZEN_CONDITION = _condition(_FROZEN)
_FROZEN_023_CONDITION = _condition(_FROZEN_023)


def upgrade() -> None:
    op.create_table(
        "listed_companies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False, server_default="NSE"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("series", sa.Text()),
        sa.Column("isin", sa.Text()),
        sa.Column("listed_on", sa.Date()),
        # ⚠ A delisting is not a deletion. A company that has left the exchange was still
        # named by sources while it was on it, and removing it would make those mentions
        # unresolvable — quietly shrinking the denominator the attribution measure divides by.
        sa.Column("delisted_at", sa.DateTime(timezone=True)),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("exchange", "symbol", name="listed_companies_unique"),
    )
    op.create_index("listed_companies_isin", "listed_companies", ["isin"])

    op.create_table(
        "candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # The vocabulary entry this candidate IS. Not an instrument: an instrument is
        # something the portfolio has an opinion about, and this is a company that has merely
        # been named.
        sa.Column(
            "listed_company_id",
            sa.Uuid(),
            sa.ForeignKey("listed_companies.id"),
            nullable=False,
        ),
        # Set only once the candidate is promoted and becomes something the system prices and
        # scores. ⚠ NULL is the normal state and costs nothing.
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id")),
        sa.Column("status", sa.Text(), nullable=False, server_default="QUEUED"),
        # Which mention put it here — so the queue can always answer "who told me about this".
        sa.Column("first_mention_id", sa.Uuid(), sa.ForeignKey("mentions.id")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        # How many separate times something has named it. A company three sources keep
        # returning to is a different proposition from one named once in passing.
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="1"),
        # ⚠ The best trust tier that has EVER named it. A candidate named once by a filing and
        # ten times by commentary is a filing-grade lead; taking the latest or the worst would
        # lose that, and tier is what the sourcing gate reads.
        sa.Column("best_trust_tier", sa.Integer(), nullable=False, server_default="3"),
        # The bottleneck it may solve, proposed by the system and approved by a person —
        # exactly like an ab_mapping, and unapproved until then.
        sa.Column("proposed_bottleneck", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status in ('QUEUED','ANALYSING','PROMOTED','DISMISSED','ALREADY_TRACKED')",
            name="candidates_status",
        ),
        sa.CheckConstraint("best_trust_tier between 1 and 3", name="candidates_tier"),
        # ⚠ Dropping a candidate demands a reason, enforced here rather than by the code that
        # writes it. A rule the application promises to honour is one a later writer forgets,
        # and this particular rule is the only record of what kinds of idea get refused.
        sa.CheckConstraint(
            "status <> 'DISMISSED' OR (dismissed_reason IS NOT NULL "
            "AND length(trim(dismissed_reason)) > 0)",
            name="candidates_dismissal_has_a_reason",
        ),
        # ⚠ A promoted candidate must point at the instrument it became, or the queue would
        # claim something is being tracked with no way to check.
        sa.CheckConstraint(
            "status <> 'PROMOTED' OR instrument_id IS NOT NULL",
            name="candidates_promotion_has_an_instrument",
        ),
        sa.UniqueConstraint("listed_company_id", name="candidates_one_per_company"),
    )
    op.create_index("candidates_by_status", "candidates", ["status", "last_seen_at"])

    # --- one vocabulary for what a source IS ------------------------------------------------
    #
    # ⚠ 019 let a `source_items.kind` be 'NEWS' while 023 registered the same thing as a
    # source of kind 'RSS_NEWS'. Two spellings for one concept, in two tables that are always
    # written together — so the first press feed ever polled failed its CHECK at insert, after
    # the fetch, after the reading, with the whole round rolled back. Aligned here rather than
    # papered over at the call site, because the call site is not where the disagreement is.
    op.drop_constraint("source_items_kind", "source_items", type_="check")
    op.create_check_constraint(
        "source_items_kind",
        "source_items",
        "kind in ('RESULTS_XBRL','RSS_EXCHANGE','RSS_NEWS','NEWS','YOUTUBE','EDGAR',"
        "'USER_DROP','MACRO')",
    )

    # --- mentions can now be about a company the portfolio does not follow -----------------
    op.alter_column("mentions", "instrument_id", nullable=True)
    op.add_column(
        "mentions",
        sa.Column("listed_company_id", sa.Uuid(), sa.ForeignKey("listed_companies.id")),
    )
    op.create_check_constraint(
        "mentions_names_exactly_one_company",
        "mentions",
        "(instrument_id IS NOT NULL) <> (listed_company_id IS NOT NULL)",
    )

    # ⚠ The guard is rebuilt rather than left alone. Its WHEN clause names the columns that
    # may not change, so a column added afterwards would sit outside it — editable after the
    # fact in a table whose whole point is that what was said cannot be unsaid.
    op.execute("DROP TRIGGER IF EXISTS mentions_utterance_frozen ON mentions;")
    op.execute(
        f"CREATE TRIGGER mentions_utterance_frozen BEFORE UPDATE ON mentions "
        f"FOR EACH ROW WHEN ({_FROZEN_CONDITION}) "
        f"EXECUTE FUNCTION mentions_utterance_is_frozen();"
    )


def downgrade() -> None:
    op.drop_constraint("source_items_kind", "source_items", type_="check")
    op.execute("DELETE FROM source_items WHERE kind in ('RSS_NEWS','EDGAR');")
    op.create_check_constraint(
        "source_items_kind",
        "source_items",
        "kind in ('RESULTS_XBRL','RSS_EXCHANGE','NEWS','YOUTUBE','USER_DROP','MACRO')",
    )
    op.execute("DROP TRIGGER IF EXISTS mentions_utterance_frozen ON mentions;")
    op.drop_constraint("mentions_names_exactly_one_company", "mentions", type_="check")
    op.drop_column("mentions", "listed_company_id")
    # ⚠ The no-delete guard refuses this, and correctly — a mention that can be removed after
    # the fact is one that never has to be counted. A downgrade is the one legitimate
    # exception, so it is lifted explicitly here rather than by weakening the trigger. Without
    # this the downgrade fails halfway, which is the worst place for a migration to stop.
    op.execute("ALTER TABLE mentions DISABLE TRIGGER mentions_no_delete;")
    try:
        op.execute("DELETE FROM mentions WHERE instrument_id IS NULL;")
    finally:
        op.execute("ALTER TABLE mentions ENABLE TRIGGER mentions_no_delete;")
    op.alter_column("mentions", "instrument_id", nullable=False)
    op.execute(
        f"CREATE TRIGGER mentions_utterance_frozen BEFORE UPDATE ON mentions "
        f"FOR EACH ROW WHEN ({_FROZEN_023_CONDITION}) "
        f"EXECUTE FUNCTION mentions_utterance_is_frozen();"
    )
    op.drop_index("candidates_by_status", table_name="candidates")
    op.drop_table("candidates")
    op.drop_index("listed_companies_isin", table_name="listed_companies")
    op.drop_table("listed_companies")
