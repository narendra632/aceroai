"""026 — what you could have bought instead

The comparison the whole exercise eventually rests on. Beating nothing is easy; beating the
alternative is the question.

⚠ **The alternative is an index FUND, not an index, and that is deliberate.** The brief asks
for Nifty 50 TRI and S&P 500 TR. A total-return index is the right *idea* — the headline price
index understates the real alternative by roughly the dividend yield, and benchmarking against
it is winning by accounting — but an index cannot be bought. An index fund's NAV is a
total-return series by construction, since dividends are reinvested into the fund, and it is
what was actually available to buy instead. It differs from the pure index by the expense ratio
(~0.2%/yr on a direct plan) and a little tracking error, **both of which are real costs a real
alternative would have charged**. So this benchmark is slightly harder to beat than a raw TRI
would be for an investor who cannot buy one, and that asymmetry is the honest direction.

⚠ It is also the only source reachable without a key. NSE's own index archive refused every
path tried on 21 Sep 2026, and niftyindices.com answered a CSV request with an HTML page — the
block-page-is-valid-XML trap this module already knows. AMFI publishes NAV history freely, and
the module already reads it for the user's own funds.

⚠ **The S&P 500 benchmark is deliberately the INR-denominated fund.** The portfolio's accounts
are in rupees, so a dollar-denominated benchmark would credit or blame the comparison for a
currency move the investor did not make a decision about. The India-domiciled fund carries the
same currency exposure the user actually has.

`benchmark_values` is append-only. A benchmark whose past could be restated is a benchmark that
can be moved under a result.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "benchmarks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # A stable name the code refers to, e.g. NIFTY50_TRI.
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # ⚠ Said out loud in the interface. A benchmark that is a proxy must announce that it
        # is one, or a comparison against it reads as a comparison against the index itself.
        sa.Column("proxy_for", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        # The AMFI scheme code whose NAV series this is.
        sa.Column("external_id", sa.Text(), nullable=False),
        # Which half of the book it is the alternative to, so a blended comparison can weight
        # by the portfolio's actual geographic split rather than by a guess.
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("region in ('IN','US')", name="benchmarks_region"),
        sa.UniqueConstraint("key", name="benchmarks_key"),
    )

    op.create_table(
        "benchmark_values",
        sa.Column("benchmark_id", sa.Uuid(), sa.ForeignKey("benchmarks.id"), primary_key=True),
        sa.Column("on_day", sa.Date(), primary_key=True),
        sa.Column("value", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("value > 0", name="benchmark_values_positive"),
    )

    op.execute(
        "CREATE TRIGGER benchmark_values_append_only BEFORE UPDATE OR DELETE ON benchmark_values "
        "FOR EACH ROW EXECUTE FUNCTION investments_append_only();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS benchmark_values_append_only ON benchmark_values;")
    op.drop_table("benchmark_values")
    op.drop_table("benchmarks")
