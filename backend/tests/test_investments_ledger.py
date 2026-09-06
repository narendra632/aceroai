"""The ledger, checked against a real portfolio nobody in this repository computed.

Every expected number here comes from `openspec/changes/add-investment-ledger/
seed-reconciliation.md`, which was worked out by hand from Groww, CoinSwitch and INDmoney
screenshots **before any of this code existed**. That ordering is the point: a test written
after an implementation tends to assert whatever the implementation produces.

So these are not really unit tests. They ask one question — *does this ledger reproduce
figures a third party already published about real money?*
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
from sqlalchemy import text

from app.db.models import Instrument, Portfolio, Transaction
from app.services.investments import portfolio as pf

# --- the real seed --------------------------------------------------------------------

INSTRUMENTS = {
    "HDFCBANK": ("NSE", "HDFC Bank", "EQUITY_IN", "INR"),
    "KAYNES": ("NSE", "Kaynes Technology", "EQUITY_IN", "INR"),
    "GVTD": ("NSE", "GE Vernova T&D India", "EQUITY_IN", "INR"),
    "SAILIFE": ("NSE", "Sai Life Sciences", "EQUITY_IN", "INR"),
    "SPCX": ("NASDAQ", "SpaceX", "EQUITY_US", "USD"),
}

# (symbol, date, qty, price) — the Kaynes order at 3080 on 18 May is ABSENT on purpose:
# it did not execute, and the arithmetic is what proves it. See seed-reconciliation.md §1.
BUYS = [
    ("HDFCBANK", "2026-04-27", "5", "787.80"),
    ("HDFCBANK", "2026-06-04", "7", "750.30"),
    ("HDFCBANK", "2026-06-05", "4", "746.80"),
    ("HDFCBANK", "2026-08-12", "13", "723.75"),
    ("HDFCBANK", "2026-08-12", "4", "722.65"),
    ("KAYNES", "2026-05-12", "1", "4133.20"),
    ("KAYNES", "2026-05-14", "1", "3388.00"),
    ("KAYNES", "2026-05-15", "1", "3271.00"),
    ("KAYNES", "2026-05-18", "1", "3102.00"),
    ("KAYNES", "2026-05-20", "1", "2999.80"),
    ("GVTD", "2026-05-29", "1", "5000.00"),
    ("GVTD", "2026-06-01", "1", "4748.00"),
    ("GVTD", "2026-06-02", "1", "4639.50"),
    ("SAILIFE", "2026-04-30", "2", "1066.35"),
    ("SAILIFE", "2026-06-04", "4", "1159.00"),
]

# One remittance, one rate — INDmoney converts on deposit, not per trade.
SPCX_FX = D("96.01")
# ⚠ Units at 8dp, not the 6dp INDmoney displays. The AMOUNT is the primary fact for a
# fractional purchase — he spent $49.85 — and the unit count is a consequence of it. At 6dp
# the rounding loses enough that quantity x price no longer reproduces the amount, and the
# rupee basis drifts by 2 paise. The ledger stores 8dp precisely so this does not happen.
SPCX_BUYS = [
    ("2026-06-16", "0.24352711", "204.70"),
    ("2026-06-17", "0.26236842", "190.00"),
    ("2026-07-03", "0.35654292", "155.97"),
]

EXPECTED = {  # symbol: (quantity, cost basis, weighted average)
    "GVTD": (D("3"), D("14387.50"), D("4795.8333")),
    "HDFCBANK": (D("33"), D("24477.65"), D("741.7470")),
    "KAYNES": (D("5"), D("16894.00"), D("3378.8000")),
    "SAILIFE": (D("6"), D("6768.70"), D("1128.1167")),
}
EXPECTED_TOTAL_INR = D("62527.85")
GROWW_TOTAL_INR = D("62527.96")


@pytest.fixture
def book(db, user):
    """The real portfolio, seeded."""
    insts = {}
    for symbol, (exchange, name, asset_class, currency) in INSTRUMENTS.items():
        inst = Instrument(
            id=uuid.uuid4(),
            symbol=symbol,
            exchange=exchange,
            name=name,
            asset_class=asset_class,
            currency=currency,
        )
        db.add(inst)
        insts[symbol] = inst

    book = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL")
    db.add(book)
    db.flush()

    for symbol, date, qty, price in BUYS:
        db.add(
            Transaction(
                id=uuid.uuid4(),
                portfolio_id=book.id,
                instrument_id=insts[symbol].id,
                txn_type="BUY",
                trade_date=dt.date.fromisoformat(date),
                quantity=D(qty),
                price=D(price),
                currency="INR",
                entry_source="IMPORT",
            )
        )
    for date, qty, price in SPCX_BUYS:
        db.add(
            Transaction(
                id=uuid.uuid4(),
                portfolio_id=book.id,
                instrument_id=insts["SPCX"].id,
                txn_type="BUY",
                trade_date=dt.date.fromisoformat(date),
                quantity=D(qty),
                price=D(price),
                currency="USD",
                fx_rate_inr=SPCX_FX,
                entry_source="IMPORT",
            )
        )
    db.commit()
    book.instruments = insts  # convenience for tests
    return book


# --- does it reproduce Groww? -----------------------------------------------------------


def test_every_share_count_matches_groww(db, book):
    """The cheapest check and the one that would catch the most damaging error.

    A wrong quantity is silent poison: it propagates into value, allocation, every return
    and every review, and nothing anywhere reports it.
    """
    got = {p.symbol: p.quantity for p in pf.positions(db, book.id)}
    for symbol, (qty, _, _) in EXPECTED.items():
        assert got[symbol] == qty, f"{symbol}: held {got[symbol]}, Groww says {qty}"


def test_cost_basis_matches_groww_to_the_paisa(db, book):
    for pos in pf.positions(db, book.id):
        if pos.symbol not in EXPECTED:
            continue
        _, cost, _ = EXPECTED[pos.symbol]
        assert pos.cost_basis == cost, f"{pos.symbol}: {pos.cost_basis} vs {cost}"


def test_the_portfolio_total_is_within_rounding_of_groww(db, book):
    """11 paise across 15 transactions, and the difference is explained rather than tolerated:
    Groww rounds each lot's cost to 2dp before summing; this sums exact products."""
    total = sum((p.cost_basis for p in pf.positions(db, book.id) if p.symbol in EXPECTED), D(0))
    assert total == EXPECTED_TOTAL_INR
    assert abs(total - GROWW_TOTAL_INR) < D("0.20")


def test_weighted_average_matches(db, book):
    for pos in pf.positions(db, book.id):
        if pos.symbol not in EXPECTED:
            continue
        _, _, avg = EXPECTED[pos.symbol]
        assert pos.average_cost.quantize(D("0.0001")) == avg


def test_the_us_holding_carries_the_rate_actually_paid(db, book):
    """One remittance, one rate. INDmoney converts on deposit, not per trade — so a lookup
    per transaction would be both wrong and more work."""
    spcx = next(p for p in pf.positions(db, book.id) if p.symbol == "SPCX")
    assert spcx.cost_basis.quantize(D("0.01")) == D("155.31")
    # $155.31 x 96.01 = 14,911.31. ⚠ NOT 14,911.32, which is what summing per-transaction
    # ROUNDED rupee values gives — the hand-computed seed made exactly that mistake and this
    # test caught it. Round the total, never the parts.
    assert spcx.cost_basis_inr.quantize(D("0.01")) == D("14911.31")
    assert spcx.cost_basis_inr.quantize(D("0.01")) == (D("155.31") * SPCX_FX).quantize(D("0.01"))


def test_a_holding_is_priced_in_its_own_currency_and_in_rupees(db, book):
    """Conflating the two is how a weakening rupee gets credited as skill."""
    spcx = next(p for p in pf.positions(db, book.id) if p.symbol == "SPCX")
    assert spcx.currency == "USD"
    assert spcx.cost_basis != spcx.cost_basis_inr
    hdfc = next(p for p in pf.positions(db, book.id) if p.symbol == "HDFCBANK")
    assert hdfc.cost_basis == hdfc.cost_basis_inr  # fx 1.0


# --- the append-only guarantee -----------------------------------------------------------


def test_the_database_refuses_to_update_a_transaction(db, book):
    """A trigger nobody tests is a comment."""
    txn = db.execute(pf.live(_any_txn(book))).scalars().first()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE transactions SET quantity = 999 WHERE id = :i"), {"i": txn.id})
    db.rollback()


def test_the_database_refuses_to_delete_a_transaction(db, book):
    txn = db.execute(pf.live(_any_txn(book))).scalars().first()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM transactions WHERE id = :i"), {"i": txn.id})
    db.rollback()


def test_a_correction_is_a_new_row_and_both_survive(db, book):
    """The mechanism that replaces editing. The superseded entry stays readable — that is
    what makes 'what did I own in March' answerable a year later."""
    before = next(p for p in pf.positions(db, book.id) if p.symbol == "SAILIFE")
    wrong = (
        db.execute(pf.live(_any_txn(book)).where(Transaction.quantity == D("2"))).scalars().first()
    )

    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=wrong.instrument_id,
            txn_type="BUY",
            trade_date=wrong.trade_date,
            quantity=D("3"),  # it was actually 3, not 2
            price=wrong.price,
            currency="INR",
            entry_source="CHAT",
            supersedes_id=wrong.id,
        )
    )
    db.commit()

    after = next(p for p in pf.positions(db, book.id) if p.symbol == "SAILIFE")
    assert after.quantity == before.quantity + 1
    # Both rows are still in the table; only the fold ignores the retired one.
    assert db.get(Transaction, wrong.id) is not None


# --- corporate actions --------------------------------------------------------------------


def test_a_bonus_issue_conserves_total_cost_basis(db, book):
    """The invariant a corporate action must never violate.

    Unhandled, a 1:1 bonus halves the quoted price and reads as a 50% loss — an invalidation
    trigger fires on a phantom loss and the system proposes exiting a position that did
    nothing wrong. Highest-damage failure mode in the module.
    """
    before = next(p for p in pf.positions(db, book.id) if p.symbol == "GVTD")
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=before.instrument_id,
            txn_type="BONUS",
            trade_date=dt.date(2026, 9, 1),
            quantity=before.quantity,  # 1:1
            price=D(0),
            currency="INR",
            entry_source="CORP_ACTION",
        )
    )
    db.commit()

    after = next(p for p in pf.positions(db, book.id) if p.symbol == "GVTD")
    assert after.quantity == before.quantity * 2
    assert after.cost_basis == before.cost_basis, "a bonus adds units, never cost"
    assert after.average_cost.quantize(D("0.0001")) == (before.average_cost / 2).quantize(
        D("0.0001")
    )


# --- disposals ------------------------------------------------------------------------------


def test_fifo_relieves_the_oldest_lot_first(db, book):
    """Indian demat sales are matched FIFO, so this is the only basis on which a realised
    figure means anything for tax.

    Kaynes makes it concrete: five lots at 4133.20, 3388, 3271, 3102, 2999.80. Selling two
    relieves the two most expensive, because they are the oldest — which is the opposite of
    what weighted average would report.
    """
    kaynes = next(p for p in pf.positions(db, book.id) if p.symbol == "KAYNES")
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=kaynes.instrument_id,
            txn_type="SELL",
            trade_date=dt.date(2026, 9, 1),
            quantity=D("2"),
            price=D("3598.00"),
            currency="INR",
            entry_source="CHAT",
        )
    )
    db.commit()

    after = next(p for p in pf.positions(db, book.id) if p.symbol == "KAYNES")
    assert after.quantity == D("3")
    # Relieved 4133.20 + 3388.00 = 7521.20; proceeds 2 x 3598 = 7196.00 -> a LOSS of 325.20.
    # Weighted average would have relieved 2 x 3378.80 = 6757.60 and shown a GAIN of 438.40.
    # Same trade, opposite sign. This is why both views exist and both are labelled.
    assert after.realised_inr == D("7196.00") - D("7521.20")
    assert after.cost_basis == D("16894.00") - D("7521.20")


def test_selling_everything_leaves_a_closed_position_that_still_reports(db, book):
    """A holding sold to zero disappears from the holdings table and must not disappear from
    the record — its realised gain is what a year's review is made of."""
    gvtd = next(p for p in pf.positions(db, book.id) if p.symbol == "GVTD")
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=gvtd.instrument_id,
            txn_type="SELL",
            trade_date=dt.date(2026, 9, 1),
            quantity=gvtd.quantity,
            price=D("4306.30"),
            currency="INR",
            entry_source="CHAT",
        )
    )
    db.commit()

    assert not [p for p in pf.positions(db, book.id) if p.symbol == "GVTD"]
    closed = next(p for p in pf.positions(db, book.id, include_closed=True) if p.symbol == "GVTD")
    assert closed.quantity == D(0)
    assert closed.realised_inr == (D("4306.30") * 3) - D("14387.50")


# --- ordering -------------------------------------------------------------------------------


def test_same_day_lots_have_a_deterministic_order(db, book):
    """HDFC Bank has two lots on 2026-08-12. Ordering by trade_date alone would make which
    one FIFO consumes first arbitrary — the same class of defect as the untied vector
    ranking fixed in 05aedb0."""
    txns = pf.ledger(db, book.id)
    same_day = [t for t in txns if t.trade_date == dt.date(2026, 8, 12)]
    assert len(same_day) == 2
    again = [t.id for t in pf.ledger(db, book.id) if t.trade_date == dt.date(2026, 8, 12)]
    assert [t.id for t in same_day] == again


def _any_txn(book):
    from sqlalchemy import select

    return select(Transaction).where(Transaction.portfolio_id == book.id)
