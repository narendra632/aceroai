"""What you could have bought instead.

Beating nothing is easy. The question the whole exercise rests on is whether this beat the
alternative — and the alternative has to be something genuinely available, priced the way it
would genuinely have been priced.

⚠ **The alternative is an index FUND, not an index.** An index cannot be bought. A fund's NAV
is a total-return series by construction and carries the expense ratio and tracking error a
real alternative would have charged, which makes it slightly *harder* to beat than a raw
total-return index — the honest direction for the asymmetry to run.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import Benchmark, BenchmarkValue, Portfolio, PriceObservation, Transaction
from app.services.investments import benchmarks
from app.services.marketdata import amfi
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


def _navs(base: D, daily: str, days: int, *, end: dt.date | None = None):
    """A NAV series compounding at `daily` a day, oldest first."""
    end = end or TODAY
    rate = D(1) + D(daily)
    out, value = [], base
    for offset in range(days, -1, -1):
        out.append((end - dt.timedelta(days=offset), value.quantize(D("0.0001"))))
        value *= rate
    return out


@pytest.fixture
def flat_feed(monkeypatch):
    """Both alternatives, rising steadily, so a comparison has something to compare."""
    series = {
        "120716": _navs(D(100), "0.001", 400),  # the Indian index fund
        "148381": _navs(D(50), "0.002", 400),  # the US one, in rupees
    }
    monkeypatch.setattr(amfi, "nav_history", lambda code, start, c=None: series[code])
    return series


@pytest.fixture
def book(db, user):
    row = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL")
    db.add(row)
    db.commit()
    return row


def _holding(db, book, symbol, asset_class, *, bought, paid, worth_now, currency="INR"):
    inst = make_instrument(
        db,
        symbol=symbol,
        exchange="NSE" if asset_class == "EQUITY_IN" else "NASDAQ",
        name=f"{symbol} Industries",
        asset_class=asset_class,
        currency=currency,
    )
    db.add(inst)
    db.flush()
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=inst.id,
            txn_type="BUY",
            trade_date=bought,
            quantity=D(10),
            price=paid,
            currency=currency,
            fx_rate_inr=D(1) if currency == "INR" else D(88),
            entry_source="IMPORT",
        )
    )
    for offset in range((TODAY - bought).days + 1):
        db.add(
            PriceObservation(
                instrument_id=inst.id,
                observed_at=dt.datetime.combine(
                    bought + dt.timedelta(days=offset), dt.time(12, 0), dt.UTC
                ),
                source=TEST_SOURCE,
                kind="CLOSE",
                price=worth_now,
                currency=currency,
            )
        )
    db.commit()
    return inst


# --- the register ------------------------------------------------------------------------


def test_both_alternatives_are_registered(db):
    rows = benchmarks.install(db)
    db.commit()

    assert {row.key for row in rows} == {"NIFTY50_TRI", "SP500_TR"}
    assert {row.region for row in rows} == {"IN", "US"}


def test_registering_twice_adds_nothing(db):
    benchmarks.install(db)
    db.commit()
    benchmarks.install(db)
    db.commit()

    assert db.execute(sa.select(sa.func.count()).select_from(Benchmark)).scalar_one() == 2


def test_every_alternative_announces_that_it_is_a_proxy(db):
    """⚠ A benchmark that is a proxy has to say so, or a comparison against it reads as a
    comparison against the index itself."""
    for row in benchmarks.install(db):
        assert row.proxy_for
        assert "index" in row.proxy_for.lower() or "return" in row.proxy_for.lower()


def test_the_us_alternative_is_the_rupee_denominated_one(db):
    """⚠ The portfolio's accounts are in rupees. A dollar-denominated benchmark would credit
    or blame the comparison for a currency move nobody made a decision about."""
    us = next(row for row in benchmarks.install(db) if row.region == "US")

    assert "rupees" in us.proxy_for


# --- fetching ------------------------------------------------------------------------------


def test_a_sync_stores_the_series(db, flat_feed):
    report = benchmarks.sync(db)
    db.commit()

    assert report["written"] == sum(len(v) for v in flat_feed.values())
    assert report["failed"] == {}
    days, values = benchmarks.series(db, "NIFTY50_TRI")
    assert len(days) == len(flat_feed["120716"])
    assert values[0] < values[-1]


def test_syncing_twice_writes_nothing_new(db, flat_feed):
    benchmarks.sync(db)
    db.commit()
    again = benchmarks.sync(db)
    db.commit()

    assert again["written"] == 0


def test_a_benchmark_value_cannot_be_rewritten(db, flat_feed):
    """⚠ A benchmark whose past could be restated is one that can be moved under a result."""
    benchmarks.sync(db)
    db.commit()

    row = db.execute(sa.select(BenchmarkValue).limit(1)).scalar_one()
    row.value = D(99999)
    with pytest.raises(sa.exc.DatabaseError):
        db.flush()
    db.rollback()


def test_one_unreachable_alternative_does_not_end_the_round(db, monkeypatch):
    """⚠ A comparison against a stale benchmark is wrong; against nothing it is unavailable,
    and the caller has to be able to tell them apart."""

    def _half(code, start, c=None):
        if code == "120716":
            raise RuntimeError("AMFI is down")
        return _navs(D(50), "0.002", 30)

    monkeypatch.setattr(amfi, "nav_history", _half)

    report = benchmarks.sync(db)
    db.commit()

    assert "NIFTY50_TRI" in report["failed"]
    assert report["written"] > 0, "the other one still landed"


# --- comparing ------------------------------------------------------------------------------


def test_the_book_is_compared_over_the_same_window(db, user, book, flat_feed):
    benchmarks.sync(db)
    _holding(
        db,
        book,
        "BENCHCO",
        "EQUITY_IN",
        bought=TODAY - dt.timedelta(days=60),
        paid=D(100),
        worth_now=D(150),
    )
    db.commit()

    result = benchmarks.compare(db, user.id, start=TODAY - dt.timedelta(days=30))

    assert result.readable
    assert result.portfolio_pct is not None
    assert all(line.change_pct is not None for line in result.lines)


def test_a_window_the_benchmark_does_not_cover_reports_nothing(db, user, book, monkeypatch):
    """⚠ A return computed from a carried-forward value at one end is a return against a date
    that never happened."""
    monkeypatch.setattr(amfi, "nav_history", lambda code, start, c=None: _navs(D(100), "0.001", 10))
    benchmarks.sync(db)
    db.commit()

    result = benchmarks.compare(db, user.id, start=TODAY - dt.timedelta(days=200))

    assert all(line.change_pct is None for line in result.lines)
    assert result.blended_pct is None
    assert not result.readable


def test_the_blend_needs_both_sides(db, user, book, monkeypatch):
    """⚠ Weighting one benchmark at 100% because the other failed would present a single index
    as the whole alternative."""

    def _half(code, start, c=None):
        if code == "120716":
            raise RuntimeError("down")
        return _navs(D(50), "0.002", 200)

    monkeypatch.setattr(amfi, "nav_history", _half)
    benchmarks.sync(db)
    db.commit()

    result = benchmarks.compare(db, user.id, start=TODAY - dt.timedelta(days=30))

    assert result.blended_pct is None


def test_the_blend_is_weighted_by_value_not_by_count(db, user, book, flat_feed):
    """⚠ Two US holdings worth a tenth of the book are not half of it, and a blend weighted by
    count would compare against an alternative nobody held."""
    benchmarks.sync(db)
    _holding(
        db,
        book,
        "BIGIN",
        "EQUITY_IN",
        bought=TODAY - dt.timedelta(days=60),
        paid=D(1000),
        worth_now=D(1000),
    )
    _holding(
        db,
        book,
        "SMALLUS",
        "EQUITY_US",
        bought=TODAY - dt.timedelta(days=60),
        paid=D(1),
        worth_now=D(1),
        currency="USD",
    )
    db.commit()

    result = benchmarks.compare(db, user.id, start=TODAY - dt.timedelta(days=30))

    assert result.weights["IN"] > result.weights["US"]
    assert result.weights["IN"] + result.weights["US"] == pytest.approx(D(1), abs=D("0.0002"))


def test_crypto_and_funds_are_flagged_rather_than_quietly_dropped(db, user, book, flat_feed):
    """⚠ The portfolio's own return genuinely includes them and no index stands in for them.
    Quietly excluding them would be picking the flattering subset; saying so is what keeps the
    number readable rather than merely available."""
    benchmarks.sync(db)
    _holding(
        db,
        book,
        "EQIN",
        "EQUITY_IN",
        bought=TODAY - dt.timedelta(days=60),
        paid=D(100),
        worth_now=D(100),
    )
    _holding(
        db,
        book,
        "COIN",
        "CRYPTO",
        bought=TODAY - dt.timedelta(days=60),
        paid=D(100),
        worth_now=D(100),
    )
    db.commit()

    result = benchmarks.compare(db, user.id, start=TODAY - dt.timedelta(days=30))

    assert result.non_equity_share > benchmarks.MISMATCH_SHARE
    assert result.caveat is not None
    assert "crypto or funds" in result.caveat


def test_a_book_that_is_all_equity_carries_no_caveat(db, user, book, flat_feed):
    benchmarks.sync(db)
    _holding(
        db,
        book,
        "EQONLY",
        "EQUITY_IN",
        bought=TODAY - dt.timedelta(days=60),
        paid=D(100),
        worth_now=D(100),
    )
    db.commit()

    result = benchmarks.compare(db, user.id, start=TODAY - dt.timedelta(days=30))

    assert result.non_equity_share == 0
    assert result.caveat is None


def test_money_added_mid_window_is_not_counted_as_a_gain(db, user, book, flat_feed):
    """⚠ The most flattering error available here. A first version subtracted net purchases
    from the change in value and reported **3915%** on the real book, because a dollar
    purchase was netted at face value against a rupee portfolio and because money added late
    into a small window swamps the arithmetic. Time-weighting is what this is for."""
    benchmarks.sync(db)
    inst = _holding(
        db,
        book,
        "LATEADD",
        "EQUITY_IN",
        bought=TODAY - dt.timedelta(days=60),
        paid=D(100),
        worth_now=D(100),
    )
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=inst.id,
            txn_type="BUY",
            trade_date=TODAY - dt.timedelta(days=5),
            quantity=D(1000),
            price=D(100),
            currency="INR",
            fx_rate_inr=D(1),
            entry_source="IMPORT",
        )
    )
    db.commit()

    result = benchmarks.compare(db, user.id, start=TODAY - dt.timedelta(days=30))

    # The price never moved, so a big deposit must not read as a return.
    assert result.portfolio_pct is not None
    assert abs(result.portfolio_pct) < D("0.05"), result.portfolio_pct


def test_a_book_with_no_history_says_so_rather_than_reporting_zero(db, user, book, flat_feed):
    benchmarks.sync(db)
    db.commit()

    result = benchmarks.compare(db, user.id, start=TODAY - dt.timedelta(days=30))

    assert result.portfolio_pct is None
    assert not result.readable
    assert result.detail


# --- over the wire -------------------------------------------------------------------------------


def test_the_benchmarks_route_returns_the_comparison(auth_client, db, user, book, flat_feed):
    benchmarks.sync(db)
    _holding(
        db,
        book,
        "WIRECO",
        "EQUITY_IN",
        bought=TODAY - dt.timedelta(days=60),
        paid=D(100),
        worth_now=D(120),
    )
    db.commit()

    body = auth_client.get("/api/investments/benchmarks?days=30").json()

    assert {line["key"] for line in body["lines"]} == {"NIFTY50_TRI", "SP500_TR"}
    assert all(line["proxy_for"] for line in body["lines"])
    # ⚠ Percentages cross as strings, like every other number in this module.
    assert isinstance(body["portfolio_pct"], str)


def test_a_review_carries_the_comparison_over_its_own_window(db, user, book, flat_feed):
    """⚠ Not a rolling year. A weekly review comparing a twelve-month portfolio figure against
    a seven-day benchmark would be comparing two different spans and reading like one."""
    from app.services.investments import reviews

    benchmarks.sync(db)
    _holding(
        db,
        book,
        "REVBENCH",
        "EQUITY_IN",
        bought=TODAY - dt.timedelta(days=60),
        paid=D(100),
        worth_now=D(120),
    )
    db.commit()

    content, _, start, end = reviews.assemble(db, user.id, "WEEKLY")

    assert content["benchmarks"]["detail"] == f"{start} to {end}"
