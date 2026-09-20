"""Schedule FA — what an Indian resident must declare about a foreign holding.

Every resident holding a foreign security reports it in Schedule FA of the income-tax return.
There is **no minimum threshold**: one fractional share of one US company is reportable, and
the penalties under the Black Money Act for omitting it are severe. What must be declared, per
security, is the date it was acquired, its initial value, its **peak value during the period**,
its closing value, and anything received from it.

Two features of that make it a problem for software rather than for a spreadsheet:

* **The period is the calendar year**, 1 January to 31 December — not the financial year every
  other Indian tax figure uses. A year ends in the middle of a tax year and the numbers for it
  cannot be taken from anything else the module reports.
* **The peak cannot be reconstructed afterwards.** It is the highest the holding was worth on
  any day, and knowing it requires having recorded what it was worth on every day.

This module exists because the second point stopped being true. Since the price feeds landed,
a close is recorded for every US holding on every trading day and a USD/INR rate beside it, so
the peak is a walk over stored observations rather than a figure someone had to think to write
down at the time. Nothing new is stored: this is a **reading** of the record, and its coverage
is reported alongside it so a thin year is visible rather than quietly averaged over.

⚠ **The rate here is the one that was actually recorded, not SBI's TT buying rate.** The
return requires conversion at the State Bank of India telegraphic-transfer buying rate for the
relevant date, which is published by the bank and is not what a market feed quotes; the two
differ by a few tenths of a percent. Every figure below therefore names the day it came from,
so the correct rate can be looked up for that day and applied. Presenting these as filing-ready
would be the more convenient lie.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Instrument, Transaction
from app.services.investments import history
from app.services.investments import portfolio as pf

ZERO = Decimal(0)

#: Types that put money in the holder's hands, for the "gross amount paid or credited" column.
_INCOME = frozenset({"DIVIDEND"})
_DISPOSAL = frozenset({"SELL", "TRANSFER_OUT"})


@dataclass
class ForeignHolding:
    """One security, one calendar year, as Schedule FA asks for it."""

    symbol: str
    name: str
    currency: str
    #: The earliest acquisition, which is the column's "date of acquiring the interest".
    acquired_on: dt.date
    #: What was paid for it, in the rupees that actually left — charges included, at the rate
    #: recorded on each purchase. Not a market value: the column asks what the investment cost.
    initial_inr: Decimal
    #: The highest it was worth on any day of the period, and the day that was.
    peak_inr: Decimal | None
    peak_on: dt.date | None
    #: Its worth on the last day of the period that carries a price, and which day that was.
    closing_inr: Decimal | None
    closing_on: dt.date | None
    #: Held on the last day of the period. A holding sold during the year still reports.
    closing_quantity: Decimal
    gross_income_inr: Decimal
    gross_proceeds_inr: Decimal
    #: ⚠ How many days of the period could actually be valued, against how many the holding
    #: was HELD for — not against the length of the period.
    #:
    #: The first version compared against the whole period and read as missing data: "priced
    #: on 97 of 263 days" for a share bought in June says the record has a hole in it, when
    #: the truth is that it was not owned until June. Coverage is about the days there was
    #: something to value, and a figure that cannot tell "not owned" from "not recorded" is
    #: reporting a fault that does not exist.
    days_valued: int
    days_held: int
    days_in_period: int

    @property
    def is_complete(self) -> bool:
        """Every day it was held carries a value."""
        return self.days_held > 0 and self.days_valued >= self.days_held


@dataclass
class ScheduleFa:
    year: int
    period_start: dt.date
    period_end: dt.date
    holdings: list[ForeignHolding] = field(default_factory=list)
    #: Calendar years this book has any foreign holding in, newest first — the year picker.
    years_available: list[int] = field(default_factory=list)


def years_with_foreign_holdings(db: Session, portfolio_id: uuid.UUID) -> list[int]:
    """Every calendar year from the first foreign purchase to now, newest first.

    Every year, not only years with a transaction: a holding bought in 2025 and still held in
    2026 is reportable in both, and a picker that offered only years with activity would hide
    exactly the years where nothing happened and the holding still had to be declared.
    """
    first = db.execute(
        sa.select(sa.func.min(Transaction.trade_date))
        .join(Instrument, Transaction.instrument_id == Instrument.id)
        .where(Transaction.portfolio_id == portfolio_id, Instrument.currency != "INR")
    ).scalar_one_or_none()
    if first is None:
        return []
    return list(range(dt.date.today().year, first.year - 1, -1))


def report(db: Session, portfolio_id: uuid.UUID, year: int) -> ScheduleFa:
    """Every foreign holding's Schedule FA figures for one calendar year.

    Walks day by day, carrying positions forward and applying each transaction once on its
    trade date — the same shape as `history.curve`, and for the same reason: re-folding the
    ledger per day is the obvious implementation and is three orders of magnitude slower.
    """
    start = dt.date(year, 1, 1)
    end = min(dt.date(year, 12, 31), dt.date.today())
    available = years_with_foreign_holdings(db, portfolio_id)

    txns = pf.ledger(db, portfolio_id)
    if not txns or end < start:
        return ScheduleFa(year, start, end, [], available)

    instruments = {
        i.id: i
        for i in db.execute(
            sa.select(Instrument).where(Instrument.id.in_({t.instrument_id for t in txns}))
        ).scalars()
    }
    foreign = {i for i, inst in instruments.items() if inst.currency != "INR"}
    if not foreign:
        return ScheduleFa(year, start, end, [], available)

    txns = [t for t in txns if t.instrument_id in foreign]
    if not txns:
        return ScheduleFa(year, start, end, [], available)

    prices = history.price_series(db, sorted(foreign))
    rates = history.fx_series(db)

    # --- the parts that come from transactions alone ------------------------------------
    acquired_on: dict[uuid.UUID, dt.date] = {}
    initial_inr: dict[uuid.UUID, Decimal] = {}
    income: dict[uuid.UUID, Decimal] = {}
    proceeds: dict[uuid.UUID, Decimal] = {}
    for txn in txns:
        key = txn.instrument_id
        fx = txn.fx_rate_inr or Decimal(1)
        gross = txn.quantity * txn.price * fx
        if txn.txn_type in pf.ACQUIRING and txn.trade_date <= end:
            acquired_on.setdefault(key, txn.trade_date)
            initial_inr[key] = initial_inr.get(key, ZERO) + gross + (txn.charges_inr or ZERO)
        if start <= txn.trade_date <= end:
            if txn.txn_type in _INCOME:
                income[key] = income.get(key, ZERO) + gross
            elif txn.txn_type in _DISPOSAL:
                proceeds[key] = proceeds.get(key, ZERO) + gross - (txn.charges_inr or ZERO)

    # --- the daily walk, for the peak and the close -------------------------------------
    by_day: dict[dt.date, list[Transaction]] = {}
    for txn in txns:
        by_day.setdefault(txn.trade_date, []).append(txn)

    positions: dict[uuid.UUID, pf.Position] = {}
    peak: dict[uuid.UUID, tuple[Decimal, dt.date]] = {}
    closing: dict[uuid.UUID, tuple[Decimal, dt.date]] = {}
    valued_days: dict[uuid.UUID, int] = {}
    held_days: dict[uuid.UUID, int] = {}
    held_in_period: set[uuid.UUID] = set()

    day = min(t.trade_date for t in txns)
    while day <= end:
        for txn in by_day.get(day, ()):
            pos = positions.get(txn.instrument_id)
            if pos is None:
                inst = instruments[txn.instrument_id]
                pos = pf.Position(
                    instrument_id=inst.id,
                    symbol=inst.symbol,
                    asset_class=inst.asset_class,
                    currency=inst.currency,
                )
                positions[txn.instrument_id] = pos
            pf._apply(pos, txn)

        if day >= start:
            for key, pos in positions.items():
                if not pos.is_open:
                    continue
                held_in_period.add(key)
                held_days[key] = held_days.get(key, 0) + 1
                price = history.value_as_of(prices.get(key), day)
                rate = history.value_as_of(rates.get(f"{pos.currency}INR"), day)
                if price is None or rate is None:
                    continue
                worth = pos.quantity * price * rate
                valued_days[key] = valued_days.get(key, 0) + 1
                if key not in peak or worth > peak[key][0]:
                    peak[key] = (worth, day)
                closing[key] = (worth, day)
        day += dt.timedelta(days=1)

    days_in_period = (end - start).days + 1
    out = [
        ForeignHolding(
            symbol=instruments[key].symbol,
            name=instruments[key].name,
            currency=instruments[key].currency,
            acquired_on=acquired_on[key],
            initial_inr=initial_inr.get(key, ZERO),
            peak_inr=peak[key][0] if key in peak else None,
            peak_on=peak[key][1] if key in peak else None,
            closing_inr=closing[key][0] if key in closing else None,
            closing_on=closing[key][1] if key in closing else None,
            closing_quantity=positions[key].quantity if key in positions else ZERO,
            gross_income_inr=income.get(key, ZERO),
            gross_proceeds_inr=proceeds.get(key, ZERO),
            days_valued=valued_days.get(key, 0),
            days_held=held_days.get(key, 0),
            days_in_period=days_in_period,
        )
        # Reportable if it was held at any point in the period OR disposed of during it —
        # a holding sold in March is still declared for that year.
        for key in sorted(
            held_in_period | set(proceeds) | set(income), key=lambda k: instruments[k].symbol
        )
        if key in acquired_on
    ]
    return ScheduleFa(year, start, end, out, available)
