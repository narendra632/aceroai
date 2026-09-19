"""The page's data, assembled — one fold, and the judgements made on top of it.

Two things are being checked that unit tests of the parts cannot reach:

* **that a total and a return computed from the same fold agree**, and
* **that a measure which cannot be computed says so** instead of arriving as a plausible
  number or a silent zero.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest

from app.db.models import FxObservation, Portfolio, Transaction
from app.services.errors import NotFound
from app.services.investments import history, overview, pricing
from tests.conftest import FX_TEST_SOURCE, TEST_SOURCE, make_instrument

TODAY = dt.date.today()


def _day(offset: int) -> dt.date:
    return TODAY - dt.timedelta(days=offset)


def _at(offset: int) -> dt.datetime:
    return dt.datetime.combine(_day(offset), dt.time(12, 0), tzinfo=dt.UTC)


# The real Kaynes lots. FIFO and weighted average disagree in SIGN on these, which is the
# whole reason both are computed and each is named.
KAYNES_LOTS = ["4133.20", "3388.00", "3271.00", "3102.00", "2999.80"]


@pytest.fixture
def book(db, user):
    instruments = {
        "KAYNES": make_instrument(
            db,
            symbol="KAYNES",
            exchange="NSE",
            name="Kaynes Technology",
            asset_class="EQUITY_IN",
            currency="INR",
        ),
        "DOGE": make_instrument(
            db,
            symbol="DOGE",
            exchange="CRYPTO",
            name="Dogecoin",
            asset_class="CRYPTO",
            currency="INR",
        ),
        "SPCX": make_instrument(
            db,
            symbol="SPCX",
            exchange="NASDAQ",
            name="SpaceX",
            asset_class="EQUITY_US",
            currency="USD",
        ),
    }
    for inst in instruments.values():
        db.add(inst)

    portfolio = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-overview", kind="REAL")
    db.add(portfolio)
    db.flush()

    def buy(symbol, days_ago, qty, price, *, currency="INR", fx=None):
        db.add(
            Transaction(
                id=uuid.uuid4(),
                portfolio_id=portfolio.id,
                instrument_id=instruments[symbol].id,
                txn_type="BUY",
                trade_date=_day(days_ago),
                quantity=D(qty),
                price=D(price),
                currency=currency,
                fx_rate_inr=D(fx) if fx else None,
                entry_source="IMPORT",
            )
        )

    for i, price in enumerate(KAYNES_LOTS):
        buy("KAYNES", 120 - i * 2, "1", price)
    buy("DOGE", 100, "1000", "0.84")
    buy("SPCX", 80, "0.86242900", "180.00", currency="USD", fx="96.01")
    db.commit()

    portfolio.instruments = instruments
    portfolio.buy = buy
    return portfolio


def _price_everything(db, book, *, days_ago=1):
    pricing.record(
        db,
        book.instruments["KAYNES"].id,
        D("3598.00"),
        "INR",
        observed_at=_at(days_ago),
        source=TEST_SOURCE,
    )
    pricing.record(
        db,
        book.instruments["DOGE"].id,
        D("0.60"),
        "INR",
        observed_at=_at(days_ago),
        source=TEST_SOURCE,
    )
    pricing.record(
        db,
        book.instruments["SPCX"].id,
        D("210.00"),
        "USD",
        observed_at=_at(days_ago),
        source=TEST_SOURCE,
    )
    db.add(
        FxObservation(
            pair="USDINR", observed_at=_at(days_ago), source=FX_TEST_SOURCE, rate=D("96.50")
        )
    )
    db.commit()


# --- the fold and its totals -------------------------------------------------------------


def test_the_summary_lists_every_open_holding(db, book, user):
    view = overview.summary(db, book.id, user.id)
    assert {h.symbol for h in view.holdings} == {"KAYNES", "DOGE", "SPCX"}
    assert view.kind == "REAL"


def test_an_unpriced_book_reports_no_value_and_names_what_is_missing(db, book, user):
    """The state this ships in. Every holding must be named, not counted."""
    view = overview.summary(db, book.id, user.id)
    assert all(h.market_value_inr is None for h in view.holdings)
    assert not view.totals.is_complete
    assert set(view.totals.unpriced) == {"KAYNES", "DOGE", "SPCX"}


def test_another_users_book_is_not_readable(db, book, other_user):
    """A portfolio id is not an authorisation. Wrong owner must be indistinguishable from
    a portfolio that does not exist."""
    with pytest.raises(NotFound):
        overview.summary(db, book.id, other_user.id)


def test_percentages_are_computed_server_side_in_exact_decimal(db, book, user):
    _price_everything(db, book)
    kaynes = next(
        h for h in overview.summary(db, book.id, user.id).holdings if h.symbol == "KAYNES"
    )
    assert isinstance(kaynes.unrealised_pct, D)
    assert kaynes.unrealised_pct == kaynes.unrealised_inr / kaynes.cost_basis_inr


def test_crypto_is_reported_apart_from_everything_else(db, book, user):
    """s.115BBH: a crypto loss offsets nothing, ever. A single netted figure would show a
    position the tax code does not permit."""
    _price_everything(db, book)
    totals = overview.summary(db, book.id, user.id).totals
    assert totals.ring_fenced_inr < 0, "DOGE bought at 0.84, marked at 0.60"
    # The main figures must not contain it.
    assert totals.market_value_inr == sum(
        h.market_value_inr
        for h in overview.summary(db, book.id, user.id).holdings
        if h.asset_class != "CRYPTO"
    )


# --- returns: both, or one with the other's absence explained ----------------------------


def test_neither_return_is_available_before_any_price_exists(db, book, user):
    view = overview.summary(db, book.id, user.id)
    kinds = {r.kind: r for r in view.returns}
    assert set(kinds) == {"money_weighted", "time_weighted"}
    for r in kinds.values():
        assert r.value is None
        assert r.unavailable_because, "an absent measure must say why it is absent"


def test_the_unavailable_reason_names_the_holdings_that_block_it(db, book, user):
    (money,) = [
        r for r in overview.summary(db, book.id, user.id).returns if r.kind == "money_weighted"
    ]
    assert "KAYNES" in money.unavailable_because
    assert "3 have none" in money.unavailable_because


def test_money_weighted_appears_once_everything_is_priced(db, book, user):
    _price_everything(db, book)
    (money,) = [
        r for r in overview.summary(db, book.id, user.id).returns if r.kind == "money_weighted"
    ]
    assert money.value is not None
    assert money.unavailable_because is None
    assert money.covers_to == TODAY


def test_time_weighted_still_says_why_it_cannot_be_computed(db, book, user):
    """⚠ The case the spec was amended for. Prices recorded today and nowhere else give ONE
    valued day — a snapshot, not a period. XIRR exists and TWR does not, and showing XIRR
    alone as "return" is the failure that reporting both exists to prevent.

    (Note prices carry forward, so pricing even yesterday already yields two valued days.
    Getting a single one takes recording today and only today.)"""
    _price_everything(db, book, days_ago=0)
    (twr,) = [
        r for r in overview.summary(db, book.id, user.id).returns if r.kind == "time_weighted"
    ]
    assert twr.value is None
    assert "at least two days" in twr.unavailable_because

    (money,) = [
        r for r in overview.summary(db, book.id, user.id).returns if r.kind == "money_weighted"
    ]
    assert money.value is not None, "the whole point: one measure exists and the other does not"


def test_time_weighted_appears_once_the_value_series_covers_a_period(db, book, user):
    _price_everything(db, book, days_ago=30)
    _price_everything(db, book, days_ago=1)
    (twr,) = [
        r for r in overview.summary(db, book.id, user.id).returns if r.kind == "time_weighted"
    ]
    assert twr.value is not None
    assert twr.covers_from == _day(30)


def test_the_terminal_value_includes_ring_fenced_holdings(db, book, user):
    """⚠ Regression. `totals.market_value_inr` excludes crypto and `ring_fenced_inr` is its
    *unrealised* gain, not its value — so building the XIRR terminal from those two
    understates it by crypto's entire cost basis and silently depresses the whole return.

    Proven by comparison: dropping DOGE's price must change the answer from "a rate" to
    "unavailable", and the rate with DOGE priced must differ from a book without DOGE at all.
    """
    _price_everything(db, book)
    with_crypto = next(
        r for r in overview.summary(db, book.id, user.id).returns if r.kind == "money_weighted"
    )
    assert with_crypto.value is not None

    # The same book with the crypto position sold off entirely — a different terminal, so a
    # different rate. If crypto were being dropped from the terminal these would coincide.
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=book.instruments["DOGE"].id,
            txn_type="SELL",
            trade_date=_day(1),
            quantity=D("1000"),
            price=D("0.60"),
            currency="INR",
            entry_source="IMPORT",
        )
    )
    db.commit()
    without = next(
        r for r in overview.summary(db, book.id, user.id).returns if r.kind == "money_weighted"
    )
    assert without.value != with_crypto.value


# --- one holding, in detail ---------------------------------------------------------------


def test_a_full_sale_gives_the_same_total_under_both_bases(db, book, user):
    """⚠ Corrected during implementation. A full disposal relieves the ENTIRE cost basis, so
    FIFO and weighted average agree by construction — there is no lot left over for the
    choice to matter to. The panel says so rather than implying a conflict that is not there."""
    _price_everything(db, book)
    sold = overview.holding_detail(db, book.id, user.id, "KAYNES").if_sold_now
    assert sold is not None
    assert sold.at_price == D("3598.00")
    assert sold.quantity == D("5")
    assert sold.realised_inr == sold.weighted_average_realised_inr
    assert sold.bases_agree is True


def test_the_bases_do_disagree_on_a_partial_sale(db, book, user):
    """Where the divergence is real — the standing Kaynes example. Five lots, sell two, and
    FIFO reports a LOSS while weighted average reports a GAIN on the same trade."""
    from app.services.investments import portfolio as pf
    from app.services.investments import taxrules

    pos = pf.position(db, book.id, book.instruments["KAYNES"].id)
    fifo = taxrules.match_fifo(pos.lots, D("2"), D("3598.00"), D(1), "EQUITY_IN", TODAY)
    fifo_total = sum(m.proceeds_inr - m.cost_inr for m in fifo)
    weighted = taxrules.match_weighted_average(pos.lots, D("2"), D("3598.00"), D(1))
    assert fifo_total < 0 < weighted, "same trade, opposite sign — this is why both are named"


def test_the_hypothetical_sale_splits_the_gain_by_holding_period(db, book, user):
    """The figure that actually changes what a sale costs. It comes from lot identity, which
    only FIFO has, and it is the reason the panel exists at all."""
    _price_everything(db, book)
    sold = overview.holding_detail(db, book.id, user.id, "KAYNES").if_sold_now
    assert sold.long_term_inr + sold.short_term_inr == sold.realised_inr
    assert sold.short_term_inr != 0, "bought ~4 months ago, so none of it is long-term yet"
    assert sold.long_term_inr == 0


def test_lots_are_listed_oldest_first_with_their_boundary(db, book, user):
    detail = overview.holding_detail(db, book.id, user.id, "KAYNES")
    assert len(detail.lots) == 5
    assert detail.lots == sorted(detail.lots, key=lambda lot: lot.trade_date)
    assert all(lot.long_term_on is not None for lot in detail.lots), "Indian equity: 12 months"


def test_a_crypto_lot_has_no_long_term_boundary_at_all(db, book, user):
    """Not a default with exceptions — crypto never becomes long-term."""
    detail = overview.holding_detail(db, book.id, user.id, "DOGE")
    assert all(lot.long_term_on is None for lot in detail.lots)
    assert detail.holding.days_to_long_term is None
    assert detail.holding.losses_ring_fenced is True


def test_a_foreign_holding_reports_the_currency_separately(db, book, user):
    """Without this, a weakening rupee credits the system with skill it does not have."""
    _price_everything(db, book)
    detail = overview.holding_detail(db, book.id, user.id, "SPCX")
    assert detail.currency_split is not None
    assert detail.currency_split.fx > 0, "96.01 paid, 96.50 now"
    assert detail.currency_split.local > 0, "180.00 paid, 210.00 now"


def test_an_indian_holding_has_no_currency_split(db, book, user):
    _price_everything(db, book)
    assert overview.holding_detail(db, book.id, user.id, "KAYNES").currency_split is None


def test_an_unpriced_holding_offers_no_hypothetical_sale(db, book, user):
    """Nothing to compute it against, so it must be absent rather than zero."""
    detail = overview.holding_detail(db, book.id, user.id, "KAYNES")
    assert detail.if_sold_now is None


def test_the_detail_carries_the_instruments_own_transactions_and_prices(db, book, user):
    _price_everything(db, book)
    detail = overview.holding_detail(db, book.id, user.id, "KAYNES")
    assert len(detail.transactions) == 5
    assert len(detail.observations) == 1
    assert all(t.instrument_id == detail.holding.instrument_id for t in detail.transactions)


def test_an_unknown_symbol_is_not_found(db, book, user):
    with pytest.raises(NotFound):
        overview.holding_detail(db, book.id, user.id, "NOSUCH")


def _points(values: list[str | None], start: dt.date) -> list[history.Point]:
    return [
        history.Point(
            day=start + dt.timedelta(days=i),
            invested_inr=D("0"),
            value_inr=D(v) if v is not None else None,
            priced=1,
            open_holdings=1,
        )
        for i, v in enumerate(values)
    ]


def test_a_purchase_at_the_end_of_a_fall_does_not_dilute_the_fall():
    """⚠ Regression, from the real book. ₹1,000 falls to ₹600 over four days; on the fifth,
    ₹10,000 is added. The picks lost 40% — the time-weighted return must say about -40%.

    The old version cut periods at purchases and weighted each purchase at 0.5, as if made
    halfway through its period. That counted the ₹10,000 as invested during the fall and
    reported -8%. On the real book it turned -58% into -15.6%.
    """
    start = dt.date(2026, 1, 1)
    points = _points(["1000", "900", "800", "700", "600", "10500"], start)
    flows = [(start + dt.timedelta(days=5), D("-10000"))]
    twr = overview._time_weighted(points, flows)
    assert twr.value == D("10500") / D("10600") * D("600") / D("1000") - 1
    assert D("-0.41") < twr.value < D("-0.40")


def test_a_purchase_day_counts_the_new_money_from_that_morning():
    """Flat book, ₹1,000 added, the combined ₹2,000 ends the day at ₹2,200: +10% on the day."""
    start = dt.date(2026, 1, 1)
    points = _points(["1000", "2200"], start)
    twr = overview._time_weighted(points, [(start + dt.timedelta(days=1), D("-1000"))])
    assert twr.value == D("0.1")


def test_the_first_purchase_day_counts_like_any_other():
    """⚠ Regression. ₹1,000 paid, worth ₹900 that evening, flat after: the picks are -10%.
    The first day used to be skipped — the chain started from the evening's ₹900 — while every
    later purchase day was counted, so the first purchase's loss simply vanished."""
    start = dt.date(2026, 1, 1)
    points = _points(["900", "900"], start)
    twr = overview._time_weighted(points, [(start, D("-1000"))])
    assert twr.value == D("-0.1")


def test_a_run_that_starts_after_the_first_purchase_starts_from_its_first_value():
    """When prices only exist from later on, nothing before them is assumed."""
    start = dt.date(2026, 1, 10)
    points = _points(["900", "990"], start)
    twr = overview._time_weighted(points, [(dt.date(2026, 1, 1), D("-1000"))])
    assert twr.value == D("0.1")


def test_the_time_weighted_figure_is_a_rolling_year():
    """⚠ Since-inception chaining never forgets: this book's first months (₹990 of crypto,
    -73%) would hold the figure near -74% through years of good decisions, and a number that
    cannot respond to what the user does next is one they stop reading. A rolling year is what
    a factsheet reports. The since-start figure is not hidden — it is in the explanation."""
    start = dt.date(2025, 1, 1)
    # A 50% fall in the first month, then flat for well over a year.
    values = ["1000", "500"] + ["500"] * 400
    twr = overview._time_weighted(_points(values, start), [(start, D("-1000"))])
    assert twr.value == 0, "the old fall is outside the window"
    assert twr.covers_to is not None and (twr.covers_to - twr.covers_from).days == 365
    assert "50.00% down" in (twr.explanation or ""), "the since-start figure must still be said"

    lifetime = overview._time_weighted(
        _points(values, start), [(start, D("-1000"))], window_days=None
    )
    assert lifetime.value == D("-0.5")
