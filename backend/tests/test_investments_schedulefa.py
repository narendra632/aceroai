"""Schedule FA — the calendar-year figures a foreign holding must be declared with.

The peak is the interesting one. It is the highest the holding was worth on **any day**, so
a reading that only looked at month-ends, or at the days a transaction happened, would be
plausible and wrong. These tests place the peak on a day nothing else is interesting about.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest

from app.db.models import FxObservation, Portfolio, PriceObservation, Transaction
from app.services.investments import schedulefa
from tests.conftest import FX_TEST_SOURCE, TEST_SOURCE, make_instrument

YEAR = dt.date.today().year - 1
"""A completed calendar year, so the period has a real end rather than today."""


def _at(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(20, 0), tzinfo=dt.UTC)


@pytest.fixture
def book(db, user):
    """One US holding bought at the start of last year, priced on four days of it."""
    us = make_instrument(
        db,
        symbol="FATEST",
        exchange="NASDAQ",
        name="Schedule FA Test Corp",
        asset_class="EQUITY_US",
        currency="USD",
    )
    inr = make_instrument(
        db,
        symbol="FADOMESTIC",
        exchange="NSE",
        name="Domestic Test Industries",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add_all([us, inr])
    portfolio = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-schedulefa", kind="REAL")
    db.add(portfolio)
    db.flush()

    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=portfolio.id,
            instrument_id=us.id,
            txn_type="BUY",
            trade_date=dt.date(YEAR, 1, 10),
            quantity=D(10),
            price=D("100.00"),
            currency="USD",
            fx_rate_inr=D("83.00"),
            charges_inr=D("250.00"),
            entry_source="IMPORT",
        )
    )
    # A domestic holding, to prove it never appears in a foreign-asset schedule.
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=portfolio.id,
            instrument_id=inr.id,
            txn_type="BUY",
            trade_date=dt.date(YEAR, 2, 1),
            quantity=D(5),
            price=D("500.00"),
            currency="INR",
            fx_rate_inr=D(1),
            entry_source="IMPORT",
        )
    )

    # ⚠ The peak sits on 1 July — a day with no transaction and no other significance. A
    # reading that sampled transaction dates or month boundaries would miss it entirely.
    for day, price in (
        (dt.date(YEAR, 1, 10), "100.00"),
        (dt.date(YEAR, 7, 1), "150.00"),
        (dt.date(YEAR, 10, 1), "120.00"),
        (dt.date(YEAR, 12, 31), "110.00"),
    ):
        db.add(
            PriceObservation(
                instrument_id=us.id,
                observed_at=_at(day),
                source=TEST_SOURCE,
                kind="CLOSE",
                price=D(price),
                currency="USD",
            )
        )
    for day, rate in ((dt.date(YEAR, 1, 10), "83.00"), (dt.date(YEAR, 12, 31), "84.00")):
        db.add(
            FxObservation(pair="USDINR", observed_at=_at(day), source=FX_TEST_SOURCE, rate=D(rate))
        )
    db.commit()

    portfolio.us = us
    portfolio.inr = inr
    return portfolio


def test_only_foreign_holdings_are_reported(db, book):
    report = schedulefa.report(db, book.id, YEAR)
    assert [h.symbol for h in report.holdings] == ["FATEST"]


def test_the_period_is_the_calendar_year_not_the_financial_year(db, book):
    """⚠ Schedule FA is the one Indian tax figure reported on 1 Jan to 31 Dec."""
    report = schedulefa.report(db, book.id, YEAR)
    assert report.period_start == dt.date(YEAR, 1, 1)
    assert report.period_end == dt.date(YEAR, 12, 31)


def test_the_peak_is_the_highest_any_day_reached(db, book):
    (holding,) = schedulefa.report(db, book.id, YEAR).holdings
    # 10 units × $150 × ₹83 (the rate carried forward from 10 Jan; 31 Dec's ₹84 is later).
    assert holding.peak_on == dt.date(YEAR, 7, 1)
    assert holding.peak_inr == D(10) * D("150.00") * D("83.00")


def test_the_closing_value_uses_the_last_day_of_the_period(db, book):
    (holding,) = schedulefa.report(db, book.id, YEAR).holdings
    assert holding.closing_on == dt.date(YEAR, 12, 31)
    assert holding.closing_inr == D(10) * D("110.00") * D("84.00")


def test_the_initial_value_is_what_was_actually_paid_including_charges(db, book):
    """Not a market value: the column asks what the investment cost."""
    (holding,) = schedulefa.report(db, book.id, YEAR).holdings
    assert holding.acquired_on == dt.date(YEAR, 1, 10)
    assert holding.initial_inr == D(10) * D("100.00") * D("83.00") + D("250.00")


def test_coverage_is_reported_rather_than_assumed(db, book):
    """⚠ A peak over the observed days is not a peak over the year, and the difference has
    to be visible or the figure quietly overstates its own authority."""
    (holding,) = schedulefa.report(db, book.id, YEAR).holdings
    assert holding.days_in_period == 365 + (1 if YEAR % 4 == 0 and YEAR % 100 != 0 else 0)
    # ⚠ Coverage is against the days HELD, not the length of the year. Bought on 10 January,
    # so the days before that are not a gap in the record — they are days it was not owned.
    expected = (dt.date(YEAR, 12, 31) - dt.date(YEAR, 1, 10)).days + 1
    assert holding.days_held == expected
    assert holding.days_valued == expected
    assert holding.is_complete, "every day it was held carries a value"
    assert holding.days_held < holding.days_in_period


def test_income_and_proceeds_are_counted_only_inside_the_period(db, book):
    for day, txn_type, qty, price in (
        (dt.date(YEAR, 6, 1), "DIVIDEND", "10", "2.00"),
        (dt.date(YEAR + 1, 6, 1), "DIVIDEND", "10", "9.00"),
    ):
        if day > dt.date.today():
            continue
        db.add(
            Transaction(
                id=uuid.uuid4(),
                portfolio_id=book.id,
                instrument_id=book.us.id,
                txn_type=txn_type,
                trade_date=day,
                quantity=D(qty),
                price=D(price),
                currency="USD",
                fx_rate_inr=D("83.50"),
                entry_source="IMPORT",
            )
        )
    db.commit()

    (holding,) = schedulefa.report(db, book.id, YEAR).holdings
    assert holding.gross_income_inr == D(10) * D("2.00") * D("83.50")


def test_a_book_with_no_foreign_holding_reports_nothing_rather_than_failing(db, user):
    portfolio = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-fa-empty", kind="REAL")
    db.add(portfolio)
    db.commit()

    report = schedulefa.report(db, portfolio.id, YEAR)
    assert report.holdings == []
    assert report.years_available == []


def test_every_year_since_the_first_foreign_purchase_is_offered(db, book):
    """Not only years with activity: a holding bought once is declared every year it is held,
    and a picker that hid the quiet years would hide exactly the ones easiest to forget."""
    report = schedulefa.report(db, book.id, YEAR)
    assert report.years_available == list(range(dt.date.today().year, YEAR - 1, -1))
