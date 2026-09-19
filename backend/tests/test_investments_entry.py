"""The write path: validation, costing, correction, and prices with an age.

One `record()` serves the API and the assistant tool, so these tests are about the rules
themselves rather than about either caller. The tool's job is to turn language into a `Draft`
and show it back; by the time this code runs, the data is structured and confirmed.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest

from app.db.models import Portfolio
from app.services.errors import Invalid
from app.services.investments import entry, pricing
from app.services.investments import portfolio as pf
from tests.conftest import TEST_SOURCE, make_instrument


@pytest.fixture
def book(db, user):
    b = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL")
    db.add(b)
    db.commit()
    return b


@pytest.fixture
def hdfc(db):
    i = make_instrument(
        db,
        symbol="HDFCBANK",
        exchange="NSE",
        name="HDFC Bank",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add(i)
    db.commit()
    return i


def _buy(db, book, symbol="HDFCBANK", qty="4", price="722.65", date="2026-08-12", **kw):
    return entry.prepare(
        db,
        book.id,
        symbol=symbol,
        txn_type="BUY",
        quantity=D(qty),
        price=D(price),
        trade_date=dt.date.fromisoformat(date),
        **kw,
    )


# --- validation ---------------------------------------------------------------------------


def test_a_draft_is_returned_for_confirmation_before_anything_is_written(db, book, hdfc):
    """The tool shows this and waits. Nothing reaches the ledger until a person agrees."""
    draft = _buy(db, book)
    assert draft.instrument_symbol == "HDFCBANK"
    assert draft.quantity == D("4")
    assert not pf.ledger(db, book.id), "preparing must not write"


def test_charges_are_computed_into_the_draft_so_the_real_cost_is_visible_first(db, book, hdfc):
    """₹2,890.60 of shares does not cost ₹2,890.60. Groww's brokerage is not zero."""
    draft = _buy(db, book)
    assert draft.gross_inr == D("2890.60")
    assert draft.charges_inr > 0
    assert draft.net_inr > draft.gross_inr


def test_a_future_dated_transaction_is_refused(db, book, hdfc):
    with pytest.raises(Invalid, match="future"):
        _buy(db, book, date=(dt.date.today() + dt.timedelta(days=1)).isoformat())


def test_a_negative_quantity_is_refused_rather_than_treated_as_a_sale(db, book, hdfc):
    """A sale is a SELL. Accepting a negative buy would put two spellings of one event into
    the ledger and make every later query choose between them."""
    with pytest.raises(Invalid, match="positive"):
        _buy(db, book, qty="-4")


def test_selling_more_than_is_held_is_refused(db, book, hdfc):
    entry.record(db, book.id, _buy(db, book, qty="4"))
    with pytest.raises(Invalid, match="holds"):
        entry.prepare(
            db,
            book.id,
            symbol="HDFCBANK",
            txn_type="SELL",
            quantity=D("10"),
            price=D("712.10"),
            trade_date=dt.date(2026, 9, 1),
        )


def test_a_foreign_holding_without_a_rate_is_refused(db, book):
    """The rate is a fact about the moment money moved and cannot be looked up later with the
    same meaning. Guessing one would put a fictional number into the cost basis forever."""
    db.add(
        make_instrument(
            db,
            symbol="SPCX",
            exchange="NASDAQ",
            name="SpaceX",
            asset_class="EQUITY_US",
            currency="USD",
        )
    )
    db.commit()
    with pytest.raises(Invalid, match="rate you actually received"):
        entry.prepare(
            db,
            book.id,
            symbol="SPCX",
            txn_type="BUY",
            quantity=D("0.24352711"),
            price=D("204.70"),
            trade_date=dt.date(2026, 6, 16),
        )


def test_a_new_instrument_needs_enough_to_identify_it(db, book):
    with pytest.raises(Invalid, match="new"):
        entry.prepare(
            db,
            book.id,
            symbol="NEWCO",
            txn_type="BUY",
            quantity=D("1"),
            price=D("100"),
            trade_date=dt.date(2026, 9, 1),
        )


# --- what is held is what is watched --------------------------------------------------------


def test_recording_a_new_holding_also_starts_tracking_it(db, book):
    """No second 'add to watchlist' action — a tracked set kept apart from holdings is one
    that will disagree with them, and the disagreement surfaces as a missed filing."""
    draft = entry.prepare(
        db,
        book.id,
        symbol="TATAPOWER",
        txn_type="BUY",
        quantity=D("12"),
        price=D("412"),
        trade_date=dt.date(2026, 9, 1),
        exchange="NSE",
        name="Tata Power",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    assert draft.creates_instrument
    assert any("starts tracking" in w for w in draft.warnings)

    entry.record(db, book.id, draft)
    found = entry.find_instrument(db, "TATAPOWER")
    assert found is not None and found.is_tracked


def test_a_renamed_fund_is_found_by_either_name(db, book):
    """HDFC Mid-Cap Opportunities Fund became HDFC Mid Cap Fund, same ISIN. Without alias
    matching, a lookup looks broken when only the label changed."""
    db.add(
        make_instrument(
            db,
            symbol="HDFCMIDCAP",
            exchange="MF_IN",
            name="HDFC Mid Cap Fund",
            asset_class="MF_IN",
            currency="INR",
            aliases=["HDFC Mid-Cap Opportunities Fund", "HDFCMIDCAPOPP"],
        )
    )
    db.commit()
    assert entry.find_instrument(db, "HDFCMIDCAP") is not None
    assert entry.find_instrument(db, "HDFCMIDCAPOPP") is not None


# --- correction ------------------------------------------------------------------------------


def test_undo_withdraws_an_entry_without_deleting_it(db, book, hdfc):
    """The UI's undo gesture. The user sees the familiar action; the ledger sees an event,
    and the database would refuse an actual delete."""
    txn = entry.record(db, book.id, _buy(db, book, qty="4"))
    assert pf.position(db, book.id, hdfc.id).quantity == D("4")

    entry.reverse(db, txn.id)

    assert pf.position(db, book.id, hdfc.id).quantity == D("0")
    from app.db.models import Transaction

    assert db.get(Transaction, txn.id) is not None, "the original must survive"


def test_undo_does_not_invent_a_sale(db, book, hdfc):
    """A contra entry would have conflated 'I typed this wrongly' with 'I sold it', creating
    a disposal that never happened and a realised gain to go with it."""
    txn = entry.record(db, book.id, _buy(db, book, qty="4", price="722.65"))
    entry.reverse(db, txn.id)
    pos = pf.position(db, book.id, hdfc.id)
    assert pos.realised_inr == D("0")


def test_an_entry_cannot_be_withdrawn_twice(db, book, hdfc):
    txn = entry.record(db, book.id, _buy(db, book))
    entry.reverse(db, txn.id)
    with pytest.raises(Invalid, match="already been corrected"):
        entry.reverse(db, txn.id)


def test_history_shows_superseded_entries_rather_than_hiding_them(db, book, hdfc):
    """Hiding them would make the history agree with the position and lose the whole point of
    an append-only ledger — that a correction is visible AS a correction."""
    txn = entry.record(db, book.id, _buy(db, book))
    entry.reverse(db, txn.id)

    rows = entry.history(db, book.id)
    assert len(rows) == 2
    assert txn.id in entry.superseded_ids(db, book.id)


# --- prices ------------------------------------------------------------------------------------


def test_a_typed_price_and_a_fetched_price_are_the_same_kind_of_fact(db, hdfc):
    """`source` is the only difference — which is what lets Phase 1b change one column value
    and nothing else."""
    pricing.record(db, hdfc.id, D("712.10"), "INR", source=f"{TEST_SOURCE}-USER")
    db.commit()
    mark = pricing.latest(db, [hdfc.id])[hdfc.id]
    assert mark.price == D("712.10")
    assert mark.source == f"{TEST_SOURCE}-USER", "the source round-trips unchanged"


def test_a_typed_price_goes_stale_exactly_like_a_dead_feed(db, hdfc):
    """⚠ Exempting typed prices would ship the staleness logic untested, to first run in
    anger against real market data."""
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=9)
    pricing.record(db, hdfc.id, D("712.10"), "INR", source=f"{TEST_SOURCE}-USER", observed_at=old)
    db.commit()
    mark = pricing.latest(db, [hdfc.id])[hdfc.id]
    assert mark.is_stale
    assert "days old" in mark.age_text


def test_the_staleness_limit_depends_on_whether_the_market_is_open(db):
    """The after-close limit looks like the loosest and is the most correct: a closing price
    IS the current price until the next open. Flagging it at 30 minutes overnight would mark
    everything stale every evening, and an alarm that fires nightly stops being read."""
    monday_noon = dt.datetime(2026, 9, 7, 11, 0, tzinfo=dt.UTC)
    monday_night = dt.datetime(2026, 9, 7, 20, 0, tzinfo=dt.UTC)
    assert pricing.staleness_limit("EQUITY_IN", at=monday_noon) == dt.timedelta(minutes=30)
    assert pricing.staleness_limit("EQUITY_IN", at=monday_night) == dt.timedelta(hours=20)


def test_a_weekend_uses_the_closed_limit(db):
    saturday = dt.datetime(2026, 9, 5, 11, 0, tzinfo=dt.UTC)
    assert pricing.staleness_limit("EQUITY_IN", at=saturday) == dt.timedelta(hours=20)


def test_crypto_and_mutual_funds_have_their_own_clocks(db):
    """Crypto trades around the clock with no close to fall back on; a NAV publishes once a
    day and a 24-hour limit would cry wolf every weekend."""
    assert pricing.staleness_limit("CRYPTO") == dt.timedelta(hours=4)
    assert pricing.staleness_limit("MF_IN") == dt.timedelta(hours=48)


# --- valuation ------------------------------------------------------------------------------------


def test_an_unpriced_holding_is_reported_as_unknown_not_as_zero(db, book, hdfc):
    """⚠ Never zero, and never a last-known value shown silently as current. A confidently
    wrong total is worse than a visibly incomplete one."""
    entry.record(db, book.id, _buy(db, book, qty="4"))
    valued = pricing.value(pf.positions(db, book.id), marks={})
    assert valued[0].market_value_inr is None
    assert not valued[0].is_priced

    t = pricing.totals(valued)
    assert "HDFCBANK" in t.unpriced
    assert not t.is_complete


def test_a_foreign_holding_without_a_rate_is_unpriced_rather_than_valued_at_par(db, book):
    """Silently treating a dollar as a rupee produces a plausible number that is never
    questioned — the worst shape an error can take."""
    inst = make_instrument(
        db,
        symbol="SPCX",
        exchange="NASDAQ",
        name="SpaceX",
        asset_class="EQUITY_US",
        currency="USD",
    )
    db.add(inst)
    db.commit()
    entry.record(
        db,
        book.id,
        entry.prepare(
            db,
            book.id,
            symbol="SPCX",
            txn_type="BUY",
            quantity=D("0.24352711"),
            price=D("204.70"),
            trade_date=dt.date(2026, 6, 16),
            fx_rate_inr=D("96.01"),
        ),
    )
    pricing.record(db, inst.id, D("147.90"), "USD", source=TEST_SOURCE)
    db.commit()

    marks = pricing.latest(db, [inst.id])
    assert pricing.value(pf.positions(db, book.id), marks, fx_inr={})[0].market_value_inr is None
    with_rate = pricing.value(pf.positions(db, book.id), marks, fx_inr={"USD": D("96.01")})
    assert with_rate[0].market_value_inr is not None


def test_crypto_is_totalled_apart_from_everything_else(db, book):
    """s.115BBH: a crypto loss offsets nothing. A single netted figure would show a position
    the tax code does not permit, and would be planned against."""
    coin = make_instrument(
        db,
        symbol="DOGE",
        exchange="CRYPTO",
        name="Dogecoin",
        asset_class="CRYPTO",
        currency="INR",
    )
    db.add(coin)
    db.commit()
    entry.record(
        db,
        book.id,
        entry.prepare(
            db,
            book.id,
            symbol="DOGE",
            txn_type="BUY",
            quantity=D("23.8916"),
            price=D("35.158"),
            trade_date=dt.date(2024, 11, 17),
        ),
    )
    pricing.record(db, coin.id, D("8.96"), "INR", source=TEST_SOURCE)
    db.commit()

    t = pricing.totals(pricing.value(pf.positions(db, book.id), pricing.latest(db, [coin.id])))
    assert t.ring_fenced_inr < 0, "the crypto loss is real"
    assert t.unrealised_inr == 0, "and it must not reduce anything else"
