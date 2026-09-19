"""What a holding is worth, and how much to trust that number.

A price is an **observation with a source and an age**. In this change the source is `USER` —
someone typed it — and in Phase 1b an adapter writes the identical row shape with a different
source. That is the whole reason valuation could be built and proven before any feed exists.

**Staleness applies regardless of source.** A price typed nine days ago is exactly as stale as
a dead feed's, and exempting typed prices would ship the staleness logic untested and first
run it in anger against real market data.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import FxObservation, Instrument, PriceObservation

ZERO = Decimal(0)

#: How old a price may be before it stops being presented as current, by asset class.
#:
#: ⚠ The limit matches **how fast the true value can actually change**, which is why one
#: number applied everywhere would be wrong in both directions at once. The after-close figure
#: looks like the loosest and is the most correct: a closing price IS the current price until
#: the next open, and flagging it at 30 minutes overnight would mark the whole portfolio stale
#: every evening — which is how a staleness signal becomes noise and stops being read.
STALE_AFTER: dict[str, dt.timedelta] = {
    "EQUITY_IN_OPEN": dt.timedelta(minutes=30),
    "EQUITY_IN_CLOSED": dt.timedelta(hours=20),
    "EQUITY_US_OPEN": dt.timedelta(minutes=30),
    "EQUITY_US_CLOSED": dt.timedelta(hours=20),
    "MF_IN": dt.timedelta(hours=48),
    "CRYPTO": dt.timedelta(hours=4),
}

#: Indian market hours, local. Used only to pick which staleness limit applies — not to decide
#: whether anything may run.
_IN_OPEN, _IN_CLOSE = dt.time(9, 15), dt.time(15, 30)


@dataclass(frozen=True)
class Mark:
    """A price, with everything needed to decide whether to believe it."""

    instrument_id: uuid.UUID
    price: Decimal
    currency: str
    observed_at: dt.datetime
    source: str
    age: dt.timedelta
    is_stale: bool
    limit: dt.timedelta

    @property
    def age_text(self) -> str:
        """Human phrasing of the age, for a UI that must always show it."""
        seconds = int(self.age.total_seconds())
        if seconds < 90:
            return "just now"
        if seconds < 5400:
            return f"{seconds // 60} min old"
        if seconds < 172800:
            return f"{seconds // 3600} h old"
        return f"{seconds // 86400} days old"


def staleness_limit(asset_class: str, *, at: dt.datetime | None = None) -> dt.timedelta:
    """The limit for this asset class right now, accounting for whether the market is open."""
    at = at or dt.datetime.now(dt.UTC)
    if asset_class in ("MF_IN", "CRYPTO"):
        return STALE_AFTER[asset_class]
    weekday = at.weekday() < 5
    local = at.time()
    open_now = weekday and _IN_OPEN <= local <= _IN_CLOSE
    return STALE_AFTER[f"{asset_class}_{'OPEN' if open_now else 'CLOSED'}"]


def record(
    db: Session,
    instrument_id: uuid.UUID,
    price: Decimal,
    currency: str,
    *,
    source: str = "USER",
    kind: str = "LAST",
    observed_at: dt.datetime | None = None,
) -> PriceObservation:
    """Write a price observation. Append-only — an existing one is never overwritten."""
    row = PriceObservation(
        instrument_id=instrument_id,
        observed_at=observed_at or dt.datetime.now(dt.UTC),
        source=source,
        kind=kind,
        price=price,
        currency=currency,
    )
    db.add(row)
    return row


def latest(
    db: Session, instrument_ids: list[uuid.UUID], *, at: dt.datetime | None = None
) -> dict[uuid.UUID, Mark]:
    """The newest usable price for each instrument, with its age judged.

    Quarantined observations are excluded rather than shown with a warning: a price the system
    has already decided not to trust is not a price, and offering it invites it being used.
    """
    if not instrument_ids:
        return {}
    at = at or dt.datetime.now(dt.UTC)

    classes = dict(
        db.execute(
            sa.select(Instrument.id, Instrument.asset_class).where(
                Instrument.id.in_(instrument_ids)
            )
        ).all()
    )

    newest = (
        sa.select(
            PriceObservation.instrument_id,
            sa.func.max(PriceObservation.observed_at).label("observed_at"),
        )
        .where(
            PriceObservation.instrument_id.in_(instrument_ids),
            PriceObservation.quality == "OK",
        )
        .group_by(PriceObservation.instrument_id)
        .subquery()
    )
    rows = db.execute(
        sa.select(PriceObservation).join(
            newest,
            sa.and_(
                PriceObservation.instrument_id == newest.c.instrument_id,
                PriceObservation.observed_at == newest.c.observed_at,
            ),
        )
    ).scalars()

    out: dict[uuid.UUID, Mark] = {}
    for row in rows:
        limit = staleness_limit(classes.get(row.instrument_id, "EQUITY_IN"), at=at)
        age = at - row.observed_at
        out[row.instrument_id] = Mark(
            instrument_id=row.instrument_id,
            price=row.price,
            currency=row.currency,
            observed_at=row.observed_at,
            source=row.source,
            age=age,
            is_stale=age > limit,
            limit=limit,
        )
    return out


def latest_fx(db: Session) -> dict[str, Decimal]:
    """The newest rate for each currency against INR, keyed by the foreign currency.

    Shaped for `value()`, which wants `{"USD": rate}`. ⚠ A currency with no observation is
    simply absent, and `value()` then reports the holding **unpriced** rather than valuing it
    at par. That is the intended path, not a gap: treating a dollar as a rupee produces a
    plausible number nobody questions.
    """
    newest = (
        sa.select(
            FxObservation.pair,
            sa.func.max(FxObservation.observed_at).label("observed_at"),
        )
        .group_by(FxObservation.pair)
        .subquery()
    )
    rows = db.execute(
        sa.select(FxObservation).join(
            newest,
            sa.and_(
                FxObservation.pair == newest.c.pair,
                FxObservation.observed_at == newest.c.observed_at,
            ),
        )
    ).scalars()
    out: dict[str, Decimal] = {}
    for row in rows:
        if row.pair.endswith("INR"):
            out[row.pair[:-3]] = row.rate
    return out


@dataclass
class ValuedPosition:
    """A holding, marked. Every money field may be None — and that is a real answer."""

    symbol: str
    asset_class: str
    currency: str
    quantity: Decimal
    cost_basis: Decimal
    cost_basis_inr: Decimal
    realised_inr: Decimal
    #: None when no price exists. ⚠ Never zero, and never a last-known value presented
    #: silently as current — a holding whose worth is unknown must say so, because a
    #: confidently wrong total is worse than a visibly incomplete one.
    market_value_inr: Decimal | None = None
    unrealised_inr: Decimal | None = None
    mark: Mark | None = None

    @property
    def is_priced(self) -> bool:
        return self.market_value_inr is not None


def value(
    positions: list,
    marks: dict[uuid.UUID, Mark],
    fx_inr: dict[str, Decimal] | None = None,
) -> list[ValuedPosition]:
    """Mark positions to their latest prices.

    `fx_inr` converts a non-INR mark. Absent a rate, the holding is reported **unpriced**
    rather than valued at par — silently treating a dollar as a rupee is the kind of error
    that produces a plausible number and is never questioned.
    """
    fx_inr = fx_inr or {}
    out = []
    for pos in positions:
        vp = ValuedPosition(
            symbol=pos.symbol,
            asset_class=pos.asset_class,
            currency=pos.currency,
            quantity=pos.quantity,
            cost_basis=pos.cost_basis,
            cost_basis_inr=pos.cost_basis_inr,
            realised_inr=pos.realised_inr,
        )
        mark = marks.get(pos.instrument_id)
        if mark is not None:
            rate = Decimal(1) if mark.currency == "INR" else fx_inr.get(mark.currency)
            if rate is not None:
                vp.mark = mark
                vp.market_value_inr = pos.quantity * mark.price * rate
                vp.unrealised_inr = vp.market_value_inr - pos.cost_basis_inr
        out.append(vp)
    return out


@dataclass
class BookTotals:
    """A portfolio total that is honest about what it could not include."""

    invested_inr: Decimal
    market_value_inr: Decimal
    unrealised_inr: Decimal
    realised_inr: Decimal
    #: Holdings with no usable price. The total silently excludes them, so it must say so.
    unpriced: list[str]
    stale: list[str]
    #: ⚠ Crypto is reported apart from everything else because under s.115BBH its losses
    #: cannot be set against any other gain — ever, in any year. A single netted figure would
    #: show a position the tax code does not permit, and would be planned against.
    ring_fenced_inr: Decimal = ZERO

    @property
    def is_complete(self) -> bool:
        return not self.unpriced


def totals(valued: list[ValuedPosition]) -> BookTotals:
    from app.services.investments.taxrules import losses_are_ring_fenced

    invested = market = unrealised = realised = ring_fenced = ZERO
    unpriced: list[str] = []
    stale: list[str] = []

    for vp in valued:
        realised += vp.realised_inr
        if not vp.is_priced:
            unpriced.append(vp.symbol)
            continue
        if vp.mark and vp.mark.is_stale:
            stale.append(vp.symbol)
        if losses_are_ring_fenced(vp.asset_class):
            ring_fenced += vp.unrealised_inr
            continue
        invested += vp.cost_basis_inr
        market += vp.market_value_inr
        unrealised += vp.unrealised_inr

    return BookTotals(
        invested_inr=invested,
        market_value_inr=market,
        unrealised_inr=unrealised,
        realised_inr=realised,
        unpriced=unpriced,
        stale=stale,
        ring_fenced_inr=ring_fenced,
    )
