"""The book over time — and an eye on movements too large to be price movements.

Two folds live here, and they have opposite characters:

* `curve` produces what the book **cost** on every day since the first trade. That is exact
  and dense, because it is derived from transactions alone.
* The value half of `curve` produces what the book was **worth**, and is only as dense as the
  prices that were actually observed. It is deliberately absent rather than approximated.

⚠ The value series is `None` on any day where even one open holding lacks a price. Assembling
a total from whatever prices happened to exist produces a line that steps whenever *coverage*
changes, and a reader cannot tell that step apart from a real movement in the portfolio. This
is `pricing.BookTotals.is_complete` extended through time, and it is the whole reason this
module is more than a loop.
"""

from __future__ import annotations

import datetime as dt
import uuid
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import FxObservation, Instrument, PriceObservation, Transaction
from app.services.investments import portfolio as pf

ZERO = Decimal(0)

#: How far apart two observations may be and still have a single session as a plausible
#: explanation for the difference between them. A weekend plus a public holiday.
MAX_GAP_DAYS = 4

#: A move larger than this, close enough together, is more likely a corporate action than a
#: price. ⚠ Deliberately not lower: a 1:4 bonus moves the price about 20% and will not trip
#: this. The real fix is the corporate-action feed, and a threshold tuned low enough to catch
#: every action would fire on ordinary volatility — which is how a warning stops being read.
MOVE_THRESHOLD = Decimal("0.25")

#: Transaction types that explain a large price move by themselves. If one of these sits in
#: the window, the corporate action IS recorded and there is nothing to warn about.
CORPORATE_ACTIONS = frozenset({"SPLIT", "BONUS"})


@dataclass(frozen=True)
class Point:
    """One day of the book.

    `invested_inr` is the **cost basis of what was held that day**, not cumulative
    contributions — so it falls when something is sold, and it is directly comparable to
    `value_inr` on the same day. Cumulative contributions answer a different question and
    would need their own line.
    """

    day: dt.date
    invested_inr: Decimal
    #: ⚠ None means "not known", never zero. See the module docstring.
    value_inr: Decimal | None
    #: How many open holdings had a usable price. Equal to `open_holdings` iff valued.
    priced: int
    open_holdings: int


@dataclass(frozen=True)
class SuspiciousMove:
    """A price change big enough, and fast enough, to suggest an unrecorded corporate action."""

    instrument_id: uuid.UUID
    symbol: str
    on: dt.date
    previous: Decimal
    current: Decimal
    #: Signed fraction: -0.5 is a halving.
    change: Decimal
    gap_days: int

    @property
    def direction(self) -> str:
        return "fell" if self.change < ZERO else "rose"


def price_series(
    db: Session, instrument_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[list[dt.date], list[Decimal]]]:
    """Every trusted price per instrument, oldest first, one per day.

    Public because `schedulefa` walks the same series for a different purpose. One reader of
    the price record, not two that can drift apart about which observations count.

    Two observations on one day collapse to the later — the same "newest wins" rule
    `pricing.latest` applies, just applied per day instead of once.
    """
    if not instrument_ids:
        return {}

    rows = db.execute(
        sa.select(PriceObservation)
        .where(
            PriceObservation.instrument_id.in_(instrument_ids),
            PriceObservation.quality == "OK",
        )
        .order_by(PriceObservation.instrument_id, PriceObservation.observed_at)
    ).scalars()

    per_day: dict[uuid.UUID, dict[dt.date, Decimal]] = defaultdict(dict)
    for row in rows:
        per_day[row.instrument_id][row.observed_at.date()] = row.price

    out: dict[uuid.UUID, tuple[list[dt.date], list[Decimal]]] = {}
    for instrument_id, by_day in per_day.items():
        days = sorted(by_day)
        out[instrument_id] = (days, [by_day[d] for d in days])
    return out


def fx_series(db: Session) -> dict[str, tuple[list[dt.date], list[Decimal]]]:
    """Every recorded exchange rate, by pair, oldest first, one per day."""
    rows = db.execute(
        sa.select(FxObservation).order_by(FxObservation.pair, FxObservation.observed_at)
    ).scalars()

    per_day: dict[str, dict[dt.date, Decimal]] = defaultdict(dict)
    for row in rows:
        per_day[row.pair][row.observed_at.date()] = row.rate

    return {
        pair: (sorted(by_day), [by_day[d] for d in sorted(by_day)])
        for pair, by_day in per_day.items()
    }


def value_as_of(series: tuple[list[dt.date], list[Decimal]] | None, day: dt.date) -> Decimal | None:
    """The last value observed on or before `day`, or None if there is none yet.

    ⚠ Carry-forward only, never backwards. A price observed tomorrow says nothing about what
    the holding was worth today, and using it would let a chart change its own past.
    """
    if series is None:
        return None
    days, values = series
    index = bisect_right(days, day)
    return values[index - 1] if index else None


def curve(
    db: Session,
    portfolio_id: uuid.UUID,
    *,
    since: dt.date | None = None,
    until: dt.date | None = None,
) -> list[Point]:
    """Cost and value, day by day.

    ⚠ Walks incrementally: positions are carried forward and each transaction is applied once,
    on its trade date. Re-folding the ledger per day is the obvious implementation and is
    **1,887× slower** on the real book — 6.3 seconds against 3.3 milliseconds — which is the
    difference between a chart and a timeout.
    """
    txns = pf.ledger(db, portfolio_id)
    if not txns:
        return []

    first = min(t.trade_date for t in txns)
    today = dt.date.today()
    start = max(since, first) if since else first
    end = min(until, today) if until else today
    if end < start:
        return []

    instruments = {
        i.id: i
        for i in db.execute(
            sa.select(Instrument).where(Instrument.id.in_({t.instrument_id for t in txns}))
        ).scalars()
    }
    prices = price_series(db, list(instruments))
    fx = fx_series(db)

    by_day: dict[dt.date, list[Transaction]] = defaultdict(list)
    for txn in txns:
        by_day[txn.trade_date].append(txn)

    positions: dict[uuid.UUID, pf.Position] = {}
    points: list[Point] = []
    day = first

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
            points.append(_point_for(day, positions, prices, fx))
        day += dt.timedelta(days=1)

    return points


def _point_for(
    day: dt.date,
    positions: dict[uuid.UUID, pf.Position],
    prices: dict[uuid.UUID, tuple[list[dt.date], list[Decimal]]],
    fx: dict[str, tuple[list[dt.date], list[Decimal]]],
) -> Point:
    invested = ZERO
    value = ZERO
    open_count = 0
    priced_count = 0

    for pos in positions.values():
        if not pos.is_open:
            continue
        open_count += 1
        invested += pos.cost_basis_inr

        price = value_as_of(prices.get(pos.instrument_id), day)
        if price is None:
            continue
        if pos.currency == "INR":
            rate: Decimal | None = Decimal(1)
        else:
            rate = value_as_of(fx.get(f"{pos.currency}INR"), day)
        if rate is None:
            continue

        priced_count += 1
        value += pos.quantity * price * rate

    complete = open_count > 0 and priced_count == open_count
    return Point(
        day=day,
        invested_inr=invested,
        value_inr=value if complete else None,
        priced=priced_count,
        open_holdings=open_count,
    )


def covered_range(points: list[Point]) -> tuple[dt.date, dt.date] | None:
    """The first and last day carrying a value, for the chart to state plainly.

    None when nothing is covered — which is the truthful answer on a book whose prices have
    never been observed, and is what the empty state renders.
    """
    valued = [p.day for p in points if p.value_inr is not None]
    return (valued[0], valued[-1]) if valued else None


def suspicious_moves(
    db: Session,
    portfolio_id: uuid.UUID,
    *,
    threshold: Decimal = MOVE_THRESHOLD,
    max_gap_days: int = MAX_GAP_DAYS,
) -> list[SuspiciousMove]:
    """Price changes better explained by a corporate action than by the market.

    Until corporate actions are ingested automatically, an unrecorded split or bonus appears
    as a catastrophic loss in a position that has lost nothing — the one failure mode of this
    module that produces a large, alarming, entirely fictional number.

    Two restrictions keep this from becoming noise:

    * **The gap limit.** Observations far apart differ for ordinary reasons. Comparing prices
      a month apart and calling the difference a single-day move would fire constantly.
    * **A recorded action explains itself.** If a SPLIT or BONUS was entered in the window,
      the corporate action *is* recorded and there is nothing to warn about.
    """
    txns = pf.ledger(db, portfolio_id)
    if not txns:
        return []

    instruments = {
        i.id: i
        for i in db.execute(
            sa.select(Instrument).where(Instrument.id.in_({t.instrument_id for t in txns}))
        ).scalars()
    }
    recorded: dict[uuid.UUID, list[dt.date]] = defaultdict(list)
    for txn in txns:
        if txn.txn_type in CORPORATE_ACTIONS:
            recorded[txn.instrument_id].append(txn.trade_date)

    out: list[SuspiciousMove] = []
    for instrument_id, (days, values) in price_series(db, list(instruments)).items():
        for i in range(1, len(days)):
            previous, current = values[i - 1], values[i]
            gap = (days[i] - days[i - 1]).days
            if gap > max_gap_days or previous <= ZERO:
                continue
            change = (current - previous) / previous
            if abs(change) <= threshold:
                continue
            if any(days[i - 1] <= on <= days[i] for on in recorded[instrument_id]):
                continue
            out.append(
                SuspiciousMove(
                    instrument_id=instrument_id,
                    symbol=instruments[instrument_id].symbol,
                    on=days[i],
                    previous=previous,
                    current=current,
                    change=change,
                    gap_days=gap,
                )
            )

    return sorted(out, key=lambda m: m.on, reverse=True)


def latest_per_instrument(moves: list[SuspiciousMove]) -> dict[uuid.UUID, SuspiciousMove]:
    """The most recent flag for each instrument — one warning per holdings row."""
    out: dict[uuid.UUID, SuspiciousMove] = {}
    for move in moves:
        if move.instrument_id not in out:
            out[move.instrument_id] = move
    return out
