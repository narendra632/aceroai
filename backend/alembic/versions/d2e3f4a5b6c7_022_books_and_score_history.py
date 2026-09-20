"""022 — a second book, and scores that are remembered rather than recomputed

Two changes, both about being able to answer a question later that cannot be answered now.

**A second paper book.** `MIRROR` starts as a copy of what is really held and then takes the
system's approved decisions on top — *"what would my portfolio look like if I had followed
Acero from here"*. `AI_CLEAN` starts from nothing and takes only those decisions — *"what has
Acero itself produced"*.

⚠ They answer different questions and one cannot be derived from the other. Seeded, the
comparison against the real book is like-for-like from day one but the machine's contribution
is buried inside a portfolio it did not choose. Empty, the machine is measured cleanly but
nothing compares to what is actually held. The overview's three categories — proposed and
done, proposed and not done, done without being proposed — need both to stay separable.

`PROPOSED_ALL` is the benchmark that asks whether the system has ideas but no timing: buy
everything it ever suggested, weight them equally, never sell. If the real book cannot beat
that, the picking works and the acting does not — which is a specific, actionable finding
rather than a vague disappointment.

**`framework_scores`.** A score is a judgement made at a moment, with the data available then
and the rules in force then. Recomputing it later with today's figures silently rewrites
history: a company that scored 4 in March and 8 in September would show 8 for both, and the
improvement — the most interesting thing about it — would be invisible.

⚠ A row is written only when a score CHANGES. Storing eleven identical rows every evening
would turn a history worth reading into a log, and the thing being recorded is the *change*.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_KINDS = (
    "kind in ('REAL','MIRROR','SHADOW_VETO','SHADOW_BUDGET','SHADOW_GATE',"
    "'PARALLEL_HYPERACTIVE')"
)
_NEW_KINDS = (
    "kind in ('REAL','MIRROR','AI_CLEAN','PROPOSED_ALL','SHADOW_VETO','SHADOW_BUDGET',"
    "'SHADOW_GATE','PARALLEL_HYPERACTIVE')"
)


def upgrade() -> None:
    op.drop_constraint("portfolios_kind", "portfolios", type_="check")
    op.create_check_constraint("portfolios_kind", "portfolios", _NEW_KINDS)

    op.create_table(
        "framework_scores",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        # The day the score DESCRIBES. Distinct from `scored_at`, which is when it was taken:
        # a catch-up run on Monday scoring Friday's facts is a fact about Friday.
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column(
            "framework_version_id",
            sa.Uuid(),
            sa.ForeignKey("framework_versions.id"),
            nullable=False,
        ),
        # ⚠ Three scores, side by side and never summed. A company can be structurally
        # essential, genuinely excellent, and still a bad purchase today — the finding an
        # average destroys.
        sa.Column("ab_score", sa.Numeric(4, 2)),
        sa.Column("ab_components", JSONB()),
        sa.Column("quality_earned", sa.Numeric(4, 2)),
        sa.Column("quality_available", sa.Numeric(4, 2)),
        sa.Column("quality_components", JSONB()),
        sa.Column("flags_yes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flags", JSONB()),
        sa.Column("quadrant", sa.Text()),
        # What it was worth when this was judged, so a score can be read beside its price.
        sa.Column("price", sa.Numeric(20, 6)),
        sa.Column("years_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("instrument_id", "as_of", name="framework_scores_one_per_day"),
    )
    op.create_index(
        "framework_scores_history", "framework_scores", ["instrument_id", "as_of"]
    )

    # Append-only: a judgement recorded at a moment, never revised afterwards.
    op.execute(
        "CREATE TRIGGER framework_scores_append_only "
        "BEFORE UPDATE OR DELETE ON framework_scores "
        "FOR EACH ROW EXECUTE FUNCTION investments_append_only();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS framework_scores_append_only ON framework_scores;")
    op.drop_index("framework_scores_history", table_name="framework_scores")
    op.drop_table("framework_scores")
    op.drop_constraint("portfolios_kind", "portfolios", type_="check")
    op.create_check_constraint("portfolios_kind", "portfolios", _OLD_KINDS)
