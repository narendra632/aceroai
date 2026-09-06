"""014 the investment ledger

Six tables, taking the database from 14 to 20. The module they serve is a research analyst
sitting on top of a bookkeeper, and this migration is the bookkeeper: no scoring, no
proposals, nothing a model touches.

**Three of these tables are INSERT-only, enforced by a trigger.** `transactions`,
`price_observations` and `fx_observations` reject UPDATE and DELETE at the database, and this
is the one place in the project where convention 6 — soft delete with an undo toast — is
deliberately not followed.

The reason is what the record is *for*. Everywhere else in Acero a deletion is a user
changing their mind about something they wrote. Here the record exists to be judged against
months later: *"what did I own in March, and what did I believe when I bought it?"* If a row
can be edited afterwards, that question has no stable answer, and every review built on it is
a story rather than a measurement. So a sale is an **event**, and a mistake is corrected by a
**counter-event** carrying `supersedes_id` — exactly as a paper ledger works.

The interface still offers undo. It is implemented as inserting the reversing row, which is
the correct place for the difference between the gesture and the ledger to live.

⚠ A trigger rather than an application-level check, because an application-level rule relies
on every future query remembering it. The trigger cannot be forgotten by a later refactor,
and `tests/test_investments_schema.py` asserts it actually fires — a trigger nobody tests is
a comment.

**Numeric, never float.** `quantity` at 8 decimals so 0.00001978 BTC and 0.862429 SPCX units
are exact; `price` at 6 so a ₹0.0025 penny NAV and a $204.70 share both fit. A column that
rounds a real holding is a column that lies on every read.

**Text + CHECK rather than Postgres enums** (convention 9): adding a value to an enum is a
migration, adding one to a CHECK is a migration that can be reviewed in a diff.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: One function, reused by every append-only table. Named for what it protects rather than
#: for what it does, so the error a developer sees names the reason.
_GUARD_FN = """
CREATE OR REPLACE FUNCTION investments_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'the % ledger is append-only: correct with a reversing entry carrying supersedes_id, '
        'never an UPDATE or DELETE', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

_APPEND_ONLY_TABLES = ("transactions", "price_observations", "fx_observations")


def upgrade() -> None:
    # --- reference -------------------------------------------------------------------
    op.create_table(
        "instruments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("isin", sa.Text()),
        sa.Column("amfi_scheme_code", sa.Text()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("sector", sa.Text()),
        # An instrument is tracked because it is held or watched. Recording a holding is
        # what sets this — there is deliberately no second "add to watchlist" action, or the
        # two would disagree and the disagreement would surface as a missed filing.
        sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default=sa.true()),
        # Aliases matter more than they look: HDFC Mid-Cap Opportunities Fund was renamed to
        # HDFC Mid Cap Fund under SEBI's naming standardisation, same ISIN. Without both
        # names an AMFI scheme lookup appears to break.
        sa.Column("aliases", sa.ARRAY(sa.Text())),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "exchange in ('NSE','BSE','NASDAQ','NYSE','AMEX','CRYPTO','MF_IN')",
            name="instruments_exchange",
        ),
        sa.CheckConstraint(
            "asset_class in ('EQUITY_IN','EQUITY_US','CRYPTO','MF_IN')",
            name="instruments_asset_class",
        ),
        sa.CheckConstraint("currency in ('INR','USD')", name="instruments_currency"),
    )
    op.create_index(
        "instruments_unique_live",
        "instruments",
        ["exchange", "symbol"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # --- books -----------------------------------------------------------------------
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # REAL is what is actually held. MIRROR is what the system's own approved decisions
        # produce, and stays empty until proposals exist. They are NOT nested: the user holds
        # things the system never suggested, and the system suggests things the user does not
        # act on. The gap between them is the measurement the module exists to produce.
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("base_currency", sa.Text(), nullable=False, server_default="INR"),
        sa.Column("mode", sa.Text(), nullable=False, server_default="BALANCED"),
        sa.Column(
            "monthly_budget_inr", sa.Numeric(14, 2), nullable=False, server_default="30000"
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "kind in ('REAL','MIRROR','SHADOW_VETO','SHADOW_BUDGET','SHADOW_GATE',"
            "'PARALLEL_HYPERACTIVE')",
            name="portfolios_kind",
        ),
        sa.CheckConstraint("mode in ('BALANCED','HYPERACTIVE')", name="portfolios_mode"),
    )

    # --- the charge schedule ---------------------------------------------------------
    # Versioned by effective date and FROZEN onto each transaction, exactly as
    # `core/pricing.py` freezes model prices. Rates change; recomputing March's charges at
    # October's rates would silently rewrite March's return.
    op.create_table(
        "charge_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("spec", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("source_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "venue in ('GROWW_EQUITY','GROWW_MF','COINSWITCH','INDMONEY_US')",
            name="charge_schedules_venue",
        ),
        sa.UniqueConstraint("venue", "effective_from", name="charge_schedules_venue_date"),
    )

    # --- the ledger ------------------------------------------------------------------
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("txn_type", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        # Stored per transaction, never looked up later: the rate at the moment money moved
        # is a fact about that moment. 1.0 for INR. Currency decomposition depends on this.
        sa.Column("fx_rate_inr", sa.Numeric(18, 8), nullable=False, server_default="1"),
        sa.Column("charges_inr", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column(
            "charge_schedule_id", sa.Uuid(), sa.ForeignKey("charge_schedules.id")
        ),
        # Withheld against a future liability, creditable and refundable — NOT a cost.
        # Booking crypto TDS or LRS TCS as expense would understate returns and double-count
        # against the flat 30% VDA rate. Kept visible and kept out of `charges_inr`.
        sa.Column("prepaid_tax_inr", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("entry_source", sa.Text(), nullable=False),
        sa.Column("entry_ref", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("transactions.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "txn_type in ('BUY','SELL','DIVIDEND','BONUS','SPLIT','RIGHTS','IPO_ALLOT',"
            "'SIP','TRANSFER_IN','TRANSFER_OUT','FEE','TDS','ADJUSTMENT')",
            name="transactions_txn_type",
        ),
        sa.CheckConstraint("currency in ('INR','USD')", name="transactions_currency"),
        sa.CheckConstraint(
            "entry_source in ('CHAT','SCREENSHOT','PROPOSAL_APPROVAL','CORP_ACTION','IMPORT')",
            name="transactions_entry_source",
        ),
    )
    op.create_index(
        "transactions_book", "transactions", ["portfolio_id", "instrument_id", "trade_date"]
    )
    op.create_index(
        "transactions_supersedes",
        "transactions",
        ["supersedes_id"],
        postgresql_where=sa.text("supersedes_id IS NOT NULL"),
    )

    # --- market facts ----------------------------------------------------------------
    # `source` is what makes Phase 1 possible without a feed: a price the user typed and a
    # price an adapter fetched are the same kind of fact, differing only here. Phase 1b
    # changes this column's value and nothing else.
    op.create_table(
        "price_observations",
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("quality", sa.Text(), nullable=False, server_default="OK"),
        sa.Column("quarantine_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("instrument_id", "observed_at", "source", "kind"),
        sa.CheckConstraint(
            "kind in ('LAST','CLOSE','NAV','ADJ_CLOSE')", name="price_observations_kind"
        ),
        sa.CheckConstraint(
            "quality in ('OK','QUARANTINED')", name="price_observations_quality"
        ),
        sa.CheckConstraint("currency in ('INR','USD')", name="price_observations_currency"),
    )
    op.create_index(
        "price_observations_latest",
        "price_observations",
        ["instrument_id", sa.text("observed_at DESC")],
    )

    op.create_table(
        "fx_observations",
        sa.Column("pair", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("pair", "observed_at", "source"),
    )

    # --- the append-only guarantee ---------------------------------------------------
    op.execute(_GUARD_FN)
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION investments_append_only()"
        )

    op.execute(
        "COMMENT ON TABLE transactions IS "
        "'APPEND-ONLY. Corrections are reversing rows carrying supersedes_id, never edits. "
        "See migration 014 for why this departs from the project soft-delete convention.'"
    )


def downgrade() -> None:
    # Triggers first: dropping a table with a trigger attached is fine, but dropping the
    # shared function while a trigger still references it is not, and the ordering is easy
    # to get wrong in a hurry.
    for table in _APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS investments_append_only()")

    op.drop_table("fx_observations")
    op.drop_index("price_observations_latest", table_name="price_observations")
    op.drop_table("price_observations")
    op.drop_index("transactions_supersedes", table_name="transactions")
    op.drop_index("transactions_book", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("charge_schedules")
    op.drop_table("portfolios")
    op.drop_index("instruments_unique_live", table_name="instruments")
    op.drop_table("instruments")
