"""The seeding script: does it write the real portfolio, and does it notice when it hasn't?

The numbers themselves are asserted in `test_investments_ledger.py` against a fixture. What
is tested here is the script's own behaviour — that running it twice is safe, and that its
reconciliation would actually catch a discrepancy rather than reporting success regardless.
"""

import uuid
from decimal import Decimal as D

import sqlalchemy as sa

from app.db.models import Instrument
from app.scripts import seed_investments as seed
from app.services.investments import costmodel
from app.services.investments import portfolio as pf


def test_seeding_reproduces_the_hand_reconciliation(db, user):
    """The check the whole change exists to pass, run through the script rather than a
    fixture — because the script is what will actually populate the real database."""
    result = seed.seed(db, user=user)
    assert seed.reconcile(db, result["portfolio_id"]) == []


def test_running_it_twice_writes_nothing_the_second_time(db, user):
    """It will be run again — after a restore, or when a later phase adds columns. A seed
    that duplicates on a second run turns a routine operation into a corrupted ledger."""
    first = seed.seed(db, user=user)
    second = seed.seed(db, user=user)
    assert first["transactions_added"] == 27
    assert second["transactions_added"] == 0
    assert seed.reconcile(db, first["portfolio_id"]) == []


def test_the_reconciliation_would_actually_catch_a_wrong_figure(db, user):
    """A check that always passes is worse than no check. This proves it can fail."""
    result = seed.seed(db, user=user)
    original = seed.EXPECTED["HDFCBANK"]
    seed.EXPECTED["HDFCBANK"] = ("999", "1.00")
    try:
        problems = seed.reconcile(db, result["portfolio_id"])
        assert any("HDFCBANK" in p for p in problems)
    finally:
        seed.EXPECTED["HDFCBANK"] = original


def test_both_books_are_created_and_the_mirror_starts_empty(db, user):
    """⚠ Not nested books. MIRROR holds what Acero's approved decisions produce and is empty
    until proposals exist; REAL is what is actually held. The gap between them is the
    measurement the module exists to produce, so they are separate from day one."""
    import sqlalchemy as sa

    from app.db.models import Portfolio

    seed.seed(db, user=user)
    kinds = {
        p.kind: p
        for p in db.execute(sa.select(Portfolio).where(Portfolio.user_id == user.id)).scalars()
    }
    assert set(kinds) == {"REAL", "MIRROR"}
    assert pf.positions(db, kinds["MIRROR"].id) == []
    assert pf.positions(db, kinds["REAL"].id)


def test_the_charge_schedules_are_written_so_costs_are_versioned(db, user):
    """Rates change. A schedule dated from when it took effect is what stops a correction six
    months from now rewriting the cost of a trade made today."""
    seed.seed(db, user=user)
    found = costmodel.schedule_for(db, "GROWW_EQUITY", __import__("datetime").date(2026, 8, 12))
    assert found is not None
    assert found.spec["brokerage_rate"] == "0.001", "Groww is not zero-brokerage"
    assert "transactioncostsreference" in found.source_note


def test_the_kaynes_order_that_never_executed_is_absent(db, user):
    """The reconciliation check working on real data. Including it gives 6 shares and
    ₹19,974; excluding it gives exactly the 5 shares and ₹16,894.00 Groww reports."""
    result = seed.seed(db, user=user)
    kaynes = next(p for p in pf.positions(db, result["portfolio_id"]) if p.symbol == "KAYNES")
    assert kaynes.quantity == D("5")
    assert kaynes.cost_basis == D("16894.00")
    assert not any(lot.unit_cost == D("3080.00") for lot in kaynes.lots)


def test_the_two_crypto_aggregates_say_that_they_are_aggregates(db, user):
    """An invented per-buy breakdown would be worse than a labelled aggregate. Anyone reading
    the ledger later must be able to tell which they are looking at."""
    import sqlalchemy as sa

    from app.db.models import Instrument, Transaction

    result = seed.seed(db, user=user)
    rows = db.execute(
        sa.select(Transaction, Instrument)
        .join(Instrument, Transaction.instrument_id == Instrument.id)
        .where(Transaction.portfolio_id == result["portfolio_id"])
    ).all()
    notes = {i.symbol: t.note for t, i in rows}
    assert "aggregate" in (notes.get("DOGE") or "")
    assert "aggregate" in (notes.get("BTC") or "")
    # The single-buy coins are exact and must NOT carry the caveat.
    assert not notes.get("ZIL")
    assert not notes.get("JASMY")


def test_the_us_holding_carries_the_rate_actually_received(db, user):
    """One remittance at 96.01, not a per-trade lookup — and it is the rate he got, markup
    included, rather than a published mid."""
    result = seed.seed(db, user=user)
    spcx = next(p for p in pf.positions(db, result["portfolio_id"]) if p.symbol == "SPCX")
    assert all(lot.fx_rate_inr == D("96.01") for lot in spcx.lots)
    assert spcx.cost_basis_inr.quantize(D("0.01")) == D("14911.31")


def test_the_seed_carries_the_identifiers_the_price_feeds_need(db, user):
    """⚠ Regression, from production. These identifiers existed only as data fixes in
    migration 016 — which mends rows a database already has. On the server the migration ran
    against an empty schema and the seed then created the instruments without them, so GE
    Vernova and both funds went silently unpriced while everything else worked.

    NSE's symbol is `GVT&D`; the bhavcopy is matched on it, and `GVTD` matches nothing."""
    seed.seed(db, user=user)
    by_symbol = {i.symbol: i for i in db.execute(sa.select(Instrument)).scalars()}

    assert "GVT&D" in by_symbol and "GVTD" not in by_symbol
    assert "GVTD" in (by_symbol["GVT&D"].aliases or []), "chat must still find the old name"
    assert by_symbol["HDFCMIDCAP"].amfi_scheme_code == "118989"
    assert by_symbol["HDFCFLEXICAP"].amfi_scheme_code == "118955"
    assert by_symbol["BTC"].coingecko_id == "bitcoin"


def test_an_instrument_stored_under_an_old_name_is_renamed_not_duplicated(db, user):
    """⚠ The dangerous half. A second row for the same holding would split its transactions
    across two instruments, and the page would show both halves as separate positions."""
    stale = Instrument(
        id=uuid.uuid4(),
        symbol="GVTD",
        exchange="NSE",
        name="GE Vernova T&D India",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add(stale)
    db.commit()
    stale_id = stale.id

    seed.seed(db, user=user)
    rows = (
        db.execute(
            sa.select(Instrument).where(
                Instrument.exchange == "NSE", Instrument.name == "GE Vernova T&D India"
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].id == stale_id
    assert rows[0].symbol == "GVT&D"
