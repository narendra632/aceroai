"""Holding periods, lot matching, and the flags that follow from them.

**This module never computes a tax liability.** It reports how long something has been held,
which side of a boundary that puts it on, and which asset-class rules apply. A number that
looks like tax owed would be relied upon, and being relied upon is exactly what it must not
be — that is an accountant's job and this is a research tool.

The boundary is a cliff, not a slope. Selling an Indian share on day 364 is taxed at 20%; on
day 366 at 12.5%. Nearly half the bill, for waiting two days — which is why acquisition dates
are stored and why `days_to_long_term` exists.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.services.investments.portfolio import Lot

#: Months of holding before a disposal is long-term. **Three explicit rules, not a default
#: with exceptions** — the US one is 24 and is the one that gets silently wrong, precisely
#: because 12 is the number everyone has in their head.
LONG_TERM_MONTHS: dict[str, int | None] = {
    "EQUITY_IN": 12,
    "MF_IN": 12,
    "EQUITY_US": 24,
    #: None means the distinction does not exist. Crypto is taxed flat under s.115BBH
    #: regardless of how long it was held.
    "CRYPTO": None,
}

#: Asset classes whose losses cannot be set against gains — anywhere, ever, in any year.
#: Netting them is the specific mistake s.115BBH punishes, so the ledger must keep them apart
#: rather than quietly summing a portfolio-wide figure.
LOSSES_CANNOT_OFFSET = frozenset({"CRYPTO"})


@dataclass(frozen=True)
class HoldingPeriod:
    """Where one lot sits relative to its boundary."""

    lot: Lot
    asset_class: str
    as_of: dt.date
    days_held: int
    #: None where the asset class has no long-term concept.
    long_term_on: dt.date | None
    is_long_term: bool

    @property
    def days_remaining(self) -> int | None:
        """Days until the boundary. None when there is no boundary, or it has passed."""
        if self.long_term_on is None or self.is_long_term:
            return None
        return (self.long_term_on - self.as_of).days


def _add_months(date: dt.date, months: int) -> dt.date:
    """Calendar-month arithmetic, clamped to the end of a short month.

    30 August plus 24 months is 30 August. 31 January plus 1 month is 28 or 29 February — a
    naive 30-day step would give 2 March and move a tax boundary by days, which is the one
    place in this module where being approximately right is being wrong.
    """
    year = date.year + (date.month - 1 + months) // 12
    month = (date.month - 1 + months) % 12 + 1
    day = min(date.day, _days_in_month(year, month))
    return dt.date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day


def long_term_date(trade_date: dt.date, asset_class: str) -> dt.date | None:
    """When a lot bought on `trade_date` becomes long-term. None if it never does."""
    months = LONG_TERM_MONTHS.get(asset_class)
    if months is None:
        return None
    return _add_months(trade_date, months)


def holding_periods(
    lots: Sequence[Lot], asset_class: str, *, as_of: dt.date | None = None
) -> list[HoldingPeriod]:
    """Where every open lot sits relative to its boundary, oldest first."""
    as_of = as_of or dt.date.today()
    out = []
    for lot in lots:
        boundary = long_term_date(lot.trade_date, asset_class)
        out.append(
            HoldingPeriod(
                lot=lot,
                asset_class=asset_class,
                as_of=as_of,
                days_held=(as_of - lot.trade_date).days,
                long_term_on=boundary,
                is_long_term=boundary is not None and as_of >= boundary,
            )
        )
    return out


def days_to_long_term(
    lots: Sequence[Lot], asset_class: str, *, as_of: dt.date | None = None
) -> int | None:
    """Days until the OLDEST still-short-term lot crosses. None when nothing is waiting.

    The oldest, because it crosses first, and because the question this answers is always
    "should this sale wait?" — which is decided by the lot FIFO would consume.
    """
    as_of = as_of or dt.date.today()
    waiting = [
        (hp.long_term_on - as_of).days
        for hp in holding_periods(lots, asset_class, as_of=as_of)
        if hp.long_term_on is not None and not hp.is_long_term and hp.lot.quantity > 0
    ]
    return min(waiting) if waiting else None


@dataclass(frozen=True)
class Matched:
    """One lot consumed by a disposal, and what it means for tax."""

    lot: Lot
    quantity: Decimal
    cost_inr: Decimal
    proceeds_inr: Decimal
    is_long_term: bool

    @property
    def gain_inr(self) -> Decimal:
        return self.proceeds_inr - self.cost_inr


def match_fifo(
    lots: Sequence[Lot],
    quantity: Decimal,
    price: Decimal,
    fx_rate: Decimal,
    asset_class: str,
    trade_date: dt.date,
) -> list[Matched]:
    """Consume lots oldest-first, splitting the disposal into its tax pieces.

    FIFO because Indian demat sales are matched that way, so it is the only basis on which a
    realised figure means anything. The result is a LIST rather than a total on purpose: one
    sale can straddle the long-term boundary, and reporting a single blended gain would hide
    the part that is taxed differently.
    """
    remaining = quantity
    out: list[Matched] = []
    for lot in lots:
        if remaining <= 0:
            break
        take = min(remaining, lot.quantity)
        if take <= 0:
            continue
        boundary = long_term_date(lot.trade_date, asset_class)
        out.append(
            Matched(
                lot=lot,
                quantity=take,
                cost_inr=take * lot.unit_cost * lot.fx_rate_inr,
                proceeds_inr=take * price * fx_rate,
                is_long_term=boundary is not None and trade_date >= boundary,
            )
        )
        remaining -= take
    return out


def match_weighted_average(
    lots: Sequence[Lot], quantity: Decimal, price: Decimal, fx_rate: Decimal
) -> Decimal:
    """Realised gain under weighted average — **the display figure, not the tax figure.**

    Kept alongside FIFO and always labelled, because the two genuinely disagree and picking
    one silently means either the tax view is wrong or the number shown contradicts the
    broker's app for no visible reason.

    Kaynes makes it concrete: five lots at 4133.20, 3388, 3271, 3102, 2999.80. Sell two and
    FIFO relieves 7521.20 for a loss, while weighted average relieves 6757.60 for a gain.
    Same trade, opposite sign.
    """
    total_qty = sum((lot.quantity for lot in lots), Decimal(0))
    if total_qty == 0:
        return Decimal(0)
    total_cost = sum((lot.quantity * lot.unit_cost * lot.fx_rate_inr for lot in lots), Decimal(0))
    unit = total_cost / total_qty
    return (quantity * price * fx_rate) - (quantity * unit)


def losses_are_ring_fenced(asset_class: str) -> bool:
    """Whether this asset's losses may be set against gains elsewhere.

    False for crypto: under s.115BBH a loss offsets nothing — not another crypto gain, not
    equity, not a future year. The portfolio view must therefore report crypto separately
    rather than folding it into a single total, or it would show a netted figure that the tax
    code does not permit and the user would plan against.
    """
    return asset_class in LOSSES_CANNOT_OFFSET
