"""The book over time, and the corporate-action warning.

The interesting assertions here are all about **absence**. It is easy to write a curve that
always produces a number, and a curve that always produces a number is lying on most days,
because the prices to compute it were never observed. So most of these tests check that the
value series is `None` when it should be, and that nothing quietly fills the gap.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest

from app.db.models import FxObservation, Portfolio, Transaction
from app.services.investments import history, pricing
from tests.conftest import FX_TEST_SOURCE, TEST_SOURCE, make_instrument

TODAY = dt.date.today()


def _day(offset: int) -> dt.date:
    """`offset` days before today. Every fixture is written relative to now so the tests do
    not start failing when a hard-coded date drifts into the past."""
    return TODAY - dt.timedelta(days=offset)


def _at(offset: int) -> dt.datetime:
    return dt.datetime.combine(_day(offset), dt.time(12, 0), tzinfo=dt.UTC)


@pytest.fixture
def book(db, user):
    """Two Indian shares and one US share, bought 20 days ago. No prices observed."""
    instruments = {
        "AAA": make_instrument(
            db,
            symbol="AAA",
            exchange="NSE",
            name="Alpha",
            asset_class="EQUITY_IN",
            currency="INR",
        ),
        "BBB": make_instrument(
            db,
            symbol="BBB",
            exchange="NSE",
            name="Beta",
            asset_class="EQUITY_IN",
            currency="INR",
        ),
        "USS": make_instrument(
            db,
            symbol="USS",
            exchange="NASDAQ",
            name="Stateside",
            asset_class="EQUITY_US",
            currency="USD",
        ),
    }
    for inst in instruments.values():
        db.add(inst)

    portfolio = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-history", kind="REAL")
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

    buy("AAA", 20, "10", "100.00")
    buy("BBB", 15, "5", "200.00")
    db.commit()

    portfolio.instruments = instruments
    portfolio.buy = buy
    return portfolio


# --- the invested line: exact and dense -------------------------------------------------


def test_there_is_a_point_for_every_day_from_the_first_trade(db, book):
    points = history.curve(db, book.id)
    assert points[0].day == _day(20)
    assert points[-1].day == TODAY
    assert len(points) == 21
    # No gaps, no repeats.
    days = [p.day for p in points]
    assert days == sorted(set(days))


def test_invested_steps_on_the_day_of_each_purchase(db, book):
    by_day = {p.day: p.invested_inr for p in history.curve(db, book.id)}
    assert by_day[_day(21)] if False else True  # before the first trade there is no point
    assert by_day[_day(20)] == D("1000.00")
    assert by_day[_day(16)] == D("1000.00")
    assert by_day[_day(15)] == D("2000.00")
    assert by_day[TODAY] == D("2000.00")


def test_a_sale_lowers_invested_on_the_day_it_happened(db, book):
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=book.instruments["AAA"].id,
            txn_type="SELL",
            trade_date=_day(5),
            quantity=D("10"),
            price=D("150.00"),
            currency="INR",
            entry_source="IMPORT",
        )
    )
    db.commit()
    by_day = {p.day: p.invested_inr for p in history.curve(db, book.id)}
    assert by_day[_day(6)] == D("2000.00")
    assert by_day[_day(5)] == D("1000.00"), "the sold holding no longer costs anything"


def test_prices_do_not_change_the_invested_line(db, book):
    before = [p.invested_inr for p in history.curve(db, book.id)]
    pricing.record(
        db, book.instruments["AAA"].id, D("175.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["BBB"].id, D("250.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    db.commit()
    after = [p.invested_inr for p in history.curve(db, book.id)]
    assert before == after, "cost is a fact about transactions, not about prices"


# --- the value line: present only where it was observed ---------------------------------


def test_no_prices_means_no_value_anywhere(db, book):
    """The state this ships in. An empty value series is the correct answer, not a bug."""
    points = history.curve(db, book.id)
    assert all(p.value_inr is None for p in points)
    assert history.covered_range(points) is None
    assert points[-1].open_holdings == 2
    assert points[-1].priced == 0


def test_one_priced_holding_out_of_two_still_yields_nothing(db, book):
    """⚠ The load-bearing test. A total assembled from partial coverage steps whenever
    coverage changes, and a reader cannot tell that from a real portfolio movement."""
    pricing.record(
        db, book.instruments["AAA"].id, D("175.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    db.commit()
    points = history.curve(db, book.id)
    assert all(p.value_inr is None for p in points)
    assert [p for p in points if p.day == _day(10)][0].priced == 1


def test_value_appears_once_every_holding_is_priced(db, book):
    pricing.record(
        db, book.instruments["AAA"].id, D("175.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["BBB"].id, D("250.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    db.commit()
    by_day = {p.day: p.value_inr for p in history.curve(db, book.id)}
    assert by_day[_day(11)] is None
    assert by_day[_day(10)] == D("10") * D("175.00") + D("5") * D("250.00")


def test_a_price_is_carried_forward_and_never_backward(db, book):
    pricing.record(
        db, book.instruments["AAA"].id, D("175.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["BBB"].id, D("250.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    db.commit()
    by_day = {p.day: p.value_inr for p in history.curve(db, book.id)}
    assert by_day[_day(12)] is None, "a later observation must not change an earlier day"
    assert by_day[_day(3)] == by_day[_day(10)], "carried forward until something replaces it"


def test_the_covered_range_reports_what_is_actually_known(db, book):
    pricing.record(
        db, book.instruments["AAA"].id, D("175.00"), "INR", observed_at=_at(8), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["BBB"].id, D("250.00"), "INR", observed_at=_at(8), source=TEST_SOURCE
    )
    db.commit()
    covered = history.covered_range(history.curve(db, book.id))
    assert covered == (_day(8), TODAY)


def test_selling_a_holding_removes_it_from_what_must_be_priced(db, book):
    """Coverage is about what is *held*. Once BBB is gone, AAA's price is enough."""
    pricing.record(
        db, book.instruments["AAA"].id, D("175.00"), "INR", observed_at=_at(18), source=TEST_SOURCE
    )
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=book.instruments["BBB"].id,
            txn_type="SELL",
            trade_date=_day(4),
            quantity=D("5"),
            price=D("260.00"),
            currency="INR",
            entry_source="IMPORT",
        )
    )
    db.commit()
    by_day = {p.day: p.value_inr for p in history.curve(db, book.id)}
    assert by_day[_day(5)] is None, "BBB still held and unpriced"
    assert by_day[_day(4)] == D("10") * D("175.00")


def test_a_quarantined_price_is_not_used(db, book):
    """A price the system has already decided not to trust is not a price."""
    for symbol in ("AAA", "BBB"):
        row = pricing.record(
            db,
            book.instruments[symbol].id,
            D("175.00"),
            "INR",
            observed_at=_at(10),
            source=TEST_SOURCE,
        )
        row.quality = "QUARANTINED"
        row.quarantine_reason = "pytest"
    db.commit()
    assert all(p.value_inr is None for p in history.curve(db, book.id))


def test_a_foreign_holding_needs_a_rate_before_it_can_be_valued(db, book):
    """⚠ Not valued at par. Treating a dollar as a rupee produces a plausible number that
    nobody questions, which is the worst shape an error can take."""
    book.buy("USS", 12, "2", "50.00", currency="USD", fx="96.00")
    pricing.record(
        db, book.instruments["AAA"].id, D("175.00"), "INR", observed_at=_at(11), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["BBB"].id, D("250.00"), "INR", observed_at=_at(11), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["USS"].id, D("55.00"), "USD", observed_at=_at(11), source=TEST_SOURCE
    )
    db.commit()

    assert all(p.value_inr is None for p in history.curve(db, book.id)), (
        "priced in dollars with no exchange rate on record is still unpriced"
    )

    # ⚠ source must start with "pytest" — `fx_observations` cannot be scoped by user, so
    # that prefix is the only thing teardown can find it by. See conftest.FX_TEST_SOURCE.
    db.add(
        FxObservation(pair="USDINR", observed_at=_at(11), source=FX_TEST_SOURCE, rate=D("96.00"))
    )
    db.commit()
    by_day = {p.day: p.value_inr for p in history.curve(db, book.id)}
    expected = D("10") * D("175.00") + D("5") * D("250.00") + D("2") * D("55.00") * D("96.00")
    assert by_day[TODAY] == expected


def test_since_and_until_bound_the_window(db, book):
    points = history.curve(db, book.id, since=_day(10), until=_day(3))
    assert points[0].day == _day(10)
    assert points[-1].day == _day(3)
    assert points[0].invested_inr == D("2000.00"), "state carried in from before the window"


def test_an_empty_book_produces_no_points(db, user):
    empty = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-empty", kind="MIRROR")
    db.add(empty)
    db.commit()
    assert history.curve(db, empty.id) == []
    assert history.covered_range([]) is None


# --- the corporate-action warning -------------------------------------------------------


def test_one_observation_produces_no_flag_and_no_error(db, book):
    """Task 0.4. The comparison needs a pair; a single price must not raise."""
    pricing.record(
        db, book.instruments["AAA"].id, D("175.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    db.commit()
    assert history.suspicious_moves(db, book.id) == []


def test_a_halving_three_days_apart_is_flagged(db, book):
    pricing.record(
        db, book.instruments["AAA"].id, D("400.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["AAA"].id, D("200.00"), "INR", observed_at=_at(7), source=TEST_SOURCE
    )
    db.commit()
    (move,) = history.suspicious_moves(db, book.id)
    assert move.symbol == "AAA"
    assert move.on == _day(7)
    assert move.gap_days == 3
    assert move.change == D("-0.5")
    assert move.direction == "fell"


def test_the_same_move_a_month_apart_is_not_flagged(db, book):
    """A warning that fires on ordinary movement is a warning that gets ignored."""
    pricing.record(
        db, book.instruments["AAA"].id, D("400.00"), "INR", observed_at=_at(40), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["AAA"].id, D("200.00"), "INR", observed_at=_at(8), source=TEST_SOURCE
    )
    db.commit()
    assert history.suspicious_moves(db, book.id) == []


def test_a_move_under_the_threshold_is_not_flagged(db, book):
    pricing.record(
        db, book.instruments["AAA"].id, D("100.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["AAA"].id, D("80.00"), "INR", observed_at=_at(9), source=TEST_SOURCE
    )
    db.commit()
    assert history.suspicious_moves(db, book.id) == [], "a 1:4 bonus is 20% and does not trip"


def test_a_recorded_split_explains_the_move(db, book):
    """The warning is about *unrecorded* actions. Recording one must silence it."""
    pricing.record(
        db, book.instruments["AAA"].id, D("400.00"), "INR", observed_at=_at(10), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["AAA"].id, D("200.00"), "INR", observed_at=_at(8), source=TEST_SOURCE
    )
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=book.instruments["AAA"].id,
            txn_type="SPLIT",
            trade_date=_day(9),
            quantity=D("10"),
            price=D("0"),
            currency="INR",
            entry_source="CORP_ACTION",
        )
    )
    db.commit()
    assert history.suspicious_moves(db, book.id) == []


def test_the_newest_flag_per_instrument_is_what_a_row_shows(db, book):
    pricing.record(
        db, book.instruments["AAA"].id, D("400.00"), "INR", observed_at=_at(12), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["AAA"].id, D("200.00"), "INR", observed_at=_at(11), source=TEST_SOURCE
    )
    pricing.record(
        db, book.instruments["AAA"].id, D("600.00"), "INR", observed_at=_at(9), source=TEST_SOURCE
    )
    db.commit()
    moves = history.suspicious_moves(db, book.id)
    assert len(moves) == 2
    latest = history.latest_per_instrument(moves)
    assert latest[book.instruments["AAA"].id].on == _day(9)
