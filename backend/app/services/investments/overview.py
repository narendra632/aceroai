"""Everything the page paints at once, from a single walk over the ledger.

Positions, marks, totals and returns are not four queries — they are one fold and three
readings of it. Computing them separately would run the walk repeatedly and, worse, let the
four answers disagree if a write landed between them.

This lives in `services/` rather than in the route because the assembly makes judgements the
assistant must make identically: which return can be computed, what a total excludes, when a
holding counts as ring-fenced. A rule implemented in only one of the two callers is a rule the
other one skips.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Instrument, Portfolio, PriceObservation, Transaction
from app.services.errors import NotFound
from app.services.investments import history, pricing, returns, taxrules
from app.services.investments import portfolio as pf

ZERO = Decimal(0)

#: Enough valued days for a chained return to mean anything. One day is a snapshot, not a
#: period, and chaining a single point produces a confident zero.
MIN_TWR_DAYS = 2


@dataclass(frozen=True)
class Return:
    """One measure of return, or a plain statement of why it is missing.

    ⚠ `value is None` is a first-class answer. The interface is required to name the missing
    measure rather than presenting the other one as "the return", because an unlabelled lone
    figure is exactly the confusion reporting both exists to prevent.
    """

    kind: str  # "money_weighted" | "time_weighted"
    label: str
    measures: str
    value: Decimal | None
    unavailable_because: str | None = None
    covers_from: dt.date | None = None
    covers_to: dt.date | None = None


@dataclass
class Holding:
    """One row of the holdings table."""

    instrument_id: uuid.UUID
    symbol: str
    name: str
    asset_class: str
    currency: str
    quantity: Decimal
    average_cost: Decimal | None
    cost_basis: Decimal
    cost_basis_inr: Decimal
    realised_inr: Decimal
    charges_inr: Decimal
    prepaid_tax_inr: Decimal
    market_value_inr: Decimal | None
    unrealised_inr: Decimal | None
    unrealised_pct: Decimal | None
    mark: pricing.Mark | None
    days_to_long_term: int | None
    losses_ring_fenced: bool
    suspicious_move: history.SuspiciousMove | None
    lots: int


@dataclass(frozen=True)
class AssetTotal:
    """One asset class, subtotalled.

    ⚠ Computed here rather than in the interface, and that is not fussiness: a subtotal is a
    displayed monetary figure, so summing it in the browser would do money arithmetic in
    binary floating point after the server had gone to the trouble of being exact.
    """

    asset_class: str
    holdings: int
    invested_inr: Decimal
    #: None when any holding in the class lacks a price — the same rule as the book total.
    market_value_inr: Decimal | None


@dataclass
class Summary:
    portfolio_id: uuid.UUID
    name: str
    kind: str
    as_of: dt.datetime
    holdings: list[Holding]
    totals: pricing.BookTotals
    by_asset_class: list[AssetTotal] = field(default_factory=list)
    #: ⚠ What EVERY holding cost, priced or not, crypto included. This is what a person
    #: means by "invested", and it is exact regardless of whether any price exists.
    #:
    #: Deliberately not `BookTotals.invested_inr`, which accumulates only priced holdings
    #: and skips ring-fenced ones so that it stays comparable with `market_value_inr`. That
    #: is right for its job and catastrophic as a headline: on a book with no prices it is
    #: **zero**, and a page reporting "Invested Rs 0" against real money is the exact
    #: confidently-wrong figure this module exists to avoid.
    cost_basis_inr: Decimal = ZERO
    #: What the holdings that cannot be valued originally cost. The page shows this beside
    #: the allocation, so "excluded" is a figure rather than a shrug.
    unpriced_cost_inr: Decimal = ZERO
    returns: list[Return] = field(default_factory=list)


def _book(db: Session, portfolio_id: uuid.UUID, user_id: uuid.UUID) -> Portfolio:
    book = db.get(Portfolio, portfolio_id)
    if book is None or book.deleted_at is not None or book.user_id != user_id:
        raise NotFound("portfolio")
    return book


def real_book(db: Session, user_id: uuid.UUID) -> Portfolio:
    """The user's REAL book. The page has no book selector — see the proposal's non-goals."""
    book = db.execute(
        sa.select(Portfolio)
        .where(
            Portfolio.user_id == user_id,
            Portfolio.kind == "REAL",
            Portfolio.deleted_at.is_(None),
        )
        .limit(1)
    ).scalar_one_or_none()
    if book is None:
        raise NotFound("no REAL portfolio — seed it before reading it")
    return book


def _pct(part: Decimal | None, whole: Decimal) -> Decimal | None:
    """A percentage, in exact decimal. ⚠ Computed here and never in the browser: the moment a
    client divides two figures it has done money arithmetic in binary floating point."""
    if part is None or whole == ZERO:
        return None
    return part / whole


def summary(db: Session, portfolio_id: uuid.UUID, user_id: uuid.UUID) -> Summary:
    """The whole page, in one fold."""
    book = _book(db, portfolio_id, user_id)
    now = dt.datetime.now(dt.UTC)

    positions = pf.positions(db, book.id)
    instrument_ids = [p.instrument_id for p in positions]
    names = dict(
        db.execute(
            sa.select(Instrument.id, Instrument.name).where(Instrument.id.in_(instrument_ids))
        ).all()
    )
    marks = pricing.latest(db, instrument_ids, at=now)
    valued = pricing.value(positions, marks, pricing.latest_fx(db))
    totals = pricing.totals(valued)
    flagged = history.latest_per_instrument(history.suspicious_moves(db, book.id))

    holdings = [
        Holding(
            instrument_id=pos.instrument_id,
            symbol=pos.symbol,
            name=names.get(pos.instrument_id, pos.symbol),
            asset_class=pos.asset_class,
            currency=pos.currency,
            quantity=pos.quantity,
            average_cost=pos.average_cost,
            cost_basis=pos.cost_basis,
            cost_basis_inr=pos.cost_basis_inr,
            realised_inr=pos.realised_inr,
            charges_inr=pos.charges_inr,
            prepaid_tax_inr=pos.prepaid_tax_inr,
            market_value_inr=vp.market_value_inr,
            unrealised_inr=vp.unrealised_inr,
            unrealised_pct=_pct(vp.unrealised_inr, pos.cost_basis_inr),
            mark=vp.mark,
            days_to_long_term=taxrules.days_to_long_term(pos.lots, pos.asset_class),
            losses_ring_fenced=taxrules.losses_are_ring_fenced(pos.asset_class),
            suspicious_move=flagged.get(pos.instrument_id),
            lots=len([lot for lot in pos.lots if lot.quantity > ZERO]),
        )
        for pos, vp in zip(positions, valued, strict=True)
    ]

    return Summary(
        portfolio_id=book.id,
        name=book.name,
        kind=book.kind,
        as_of=now,
        holdings=holdings,
        totals=totals,
        by_asset_class=_by_asset_class(holdings),
        cost_basis_inr=sum((h.cost_basis_inr for h in holdings), ZERO),
        unpriced_cost_inr=sum(
            (h.cost_basis_inr for h in holdings if h.market_value_inr is None), ZERO
        ),
        returns=_returns(db, book.id, totals, valued),
    )


def _by_asset_class(holdings: list[Holding]) -> list[AssetTotal]:
    """Subtotals per asset class, in the order the interface renders them."""
    order: list[str] = []
    grouped: dict[str, list[Holding]] = {}
    for h in holdings:
        if h.asset_class not in grouped:
            grouped[h.asset_class] = []
            order.append(h.asset_class)
        grouped[h.asset_class].append(h)

    out = []
    for asset_class in order:
        rows = grouped[asset_class]
        complete = all(h.market_value_inr is not None for h in rows)
        out.append(
            AssetTotal(
                asset_class=asset_class,
                holdings=len(rows),
                invested_inr=sum((h.cost_basis_inr for h in rows), ZERO),
                market_value_inr=(
                    sum((h.market_value_inr for h in rows if h.market_value_inr), ZERO)
                    if complete
                    else None
                ),
            )
        )
    return out


def _returns(
    db: Session,
    portfolio_id: uuid.UUID,
    totals: pricing.BookTotals,
    valued: list[pricing.ValuedPosition],
) -> list[Return]:
    """Both measures, or the one that exists with the other's absence explained."""
    txns = pf.ledger(db, portfolio_id)
    flows = pf.cash_flows(txns)
    points = history.curve(db, portfolio_id)
    return [_money_weighted(flows, totals, valued), _time_weighted(points, flows)]


def _money_weighted(
    flows: list[tuple[dt.date, Decimal]],
    totals: pricing.BookTotals,
    valued: list[pricing.ValuedPosition],
) -> Return:
    kind, label = "money_weighted", "XIRR"
    measures = "your timing — when money went in, not just what it bought"

    if not flows:
        return Return(kind, label, measures, None, "nothing has been bought yet")
    if not totals.is_complete:
        missing = ", ".join(totals.unpriced)
        return Return(
            kind,
            label,
            measures,
            None,
            f"needs a price for every holding; {len(totals.unpriced)} have none ({missing})",
        )

    # The terminal value closes the series: the money that would come back today. Realised
    # proceeds are already in `flows` as positive entries, so only open value belongs here.
    #
    # ⚠ Summed from `valued`, NOT from `totals.market_value_inr`. That figure deliberately
    # excludes ring-fenced holdings, and `ring_fenced_inr` is their *unrealised* gain rather
    # than their value — so adding the two would understate the terminal by crypto's entire
    # cost basis and quietly depress the whole portfolio's return.
    #
    # Every holding belongs here regardless of ring-fencing: s.115BBH governs which losses may
    # offset which gains for TAX, and this is a measure of what the money actually did. The
    # tax separation stays where it belongs, in the totals.
    terminal = sum((vp.market_value_inr for vp in valued if vp.is_priced), ZERO)
    rate = returns.xirr([*flows, (dt.date.today(), terminal)])
    if rate is None:
        return Return(kind, label, measures, None, "the cash flows do not converge on a rate")
    return Return(kind, label, measures, rate, covers_from=flows[0][0], covers_to=dt.date.today())


def _time_weighted(points: list[history.Point], flows: list[tuple[dt.date, Decimal]]) -> Return:
    """Chained across sub-periods delimited by cash flows.

    ⚠ Computable only over days the value series actually covers, which is why this is the
    measure that goes missing first. It needs a valuation at each boundary, and a valuation
    needs an observed price for every holding — so a book whose prices have never been
    recorded can produce XIRR and cannot produce this.
    """
    kind, label = "time_weighted", "TWR"
    measures = "the ideas — with the effect of cash-flow timing removed"

    run = _longest_valued_run(points)
    if len(run) < MIN_TWR_DAYS:
        return Return(
            kind,
            label,
            measures,
            None,
            "needs the value of the book on at least two days, which needs a price for every "
            "holding on those days",
        )

    by_day: dict[dt.date, Decimal] = {}
    for day, amount in flows:
        by_day[day] = by_day.get(day, ZERO) + amount

    periods: list[returns.SubPeriod] = []
    start = run[0]
    pending = ZERO
    for point in run[1:]:
        flow = by_day.get(point.day, ZERO)
        pending += flow
        if flow != ZERO:
            periods.append(
                returns.SubPeriod(
                    start_value=start.value_inr,
                    end_value=point.value_inr,
                    # `flows` are signed from the investor's side: money out is negative. A
                    # purchase ADDS to the portfolio, so the sign flips crossing the boundary.
                    net_flow=-pending,
                )
            )
            start, pending = point, ZERO
    if start is not run[-1]:
        periods.append(
            returns.SubPeriod(
                start_value=start.value_inr, end_value=run[-1].value_inr, net_flow=-pending
            )
        )

    rate = returns.twr(periods)
    if rate is None:
        return Return(kind, label, measures, None, "no complete sub-period to chain")
    return Return(kind, label, measures, rate, covers_from=run[0].day, covers_to=run[-1].day)


def _longest_valued_run(points: list[history.Point]) -> list[history.Point]:
    """The most recent unbroken stretch of valued days.

    Unbroken because a chained return across a hole would treat the missing days as though
    nothing happened in them. Most recent because that is the stretch a reader is asking about.
    """
    best: list[history.Point] = []
    run: list[history.Point] = []
    for point in points:
        if point.value_inr is None:
            run = []
            continue
        run.append(point)
        if len(run) >= len(best):
            best = run
    return best


def cash_effect_inr(txn: Transaction) -> Decimal:
    """What one transaction did to the bank balance, signed: out is negative.

    ⚠ Mirrors `portfolio.cash_flows` exactly, including that **prepaid tax is not part of
    it** — TDS and TCS are withheld against a future liability and are creditable, so
    counting them as money spent would understate returns and double-count against the flat
    VDA rate. `test_investments_api.py` asserts the two agree on every transaction in a book,
    because a display figure that drifts from the figure returns are computed on is a bug
    nobody would notice.
    """
    fx = txn.fx_rate_inr or Decimal(1)
    gross = txn.quantity * txn.price * fx
    charges = txn.charges_inr or ZERO
    if txn.txn_type in pf.ACQUIRING:
        return -(gross + charges)
    if txn.txn_type in pf.DISPOSING or txn.txn_type == "DIVIDEND":
        return gross - charges
    return ZERO


# --- one holding, in detail -------------------------------------------------------------


@dataclass
class LotView:
    trade_date: dt.date
    quantity: Decimal
    unit_cost: Decimal
    fx_rate_inr: Decimal
    cost_inr: Decimal
    days_held: int
    long_term_on: dt.date | None
    is_long_term: bool
    days_remaining: int | None


@dataclass
class IfSoldNow:
    """Selling the whole holding at the current mark.

    ⚠ **On a full disposal FIFO and weighted average agree by construction**, because both
    relieve the entire cost basis — there is no lot left over for the choice to matter to.
    They diverge on a *partial* sale, which is where Kaynes' five lots famously produce a FIFO
    loss and a weighted-average gain on the same trade.

    That is worth stating rather than hiding, because the useful thing here is not a second
    number: it is `long_term_inr` against `short_term_inr`. That split comes from lot
    identity, which only FIFO has, and it is what actually changes what a sale costs.
    """

    at_price: Decimal
    quantity: Decimal
    realised_inr: Decimal
    long_term_inr: Decimal
    short_term_inr: Decimal
    weighted_average_realised_inr: Decimal
    #: True whenever the whole holding is sold. Kept as data rather than a comment so the
    #: interface can say "Groww would show the same figure" instead of implying a conflict.
    bases_agree: bool


@dataclass
class HoldingDetail:
    holding: Holding
    lots: list[LotView]
    if_sold_now: IfSoldNow | None
    currency_split: returns.CurrencySplit | None
    transactions: list[Transaction]
    observations: list[PriceObservation]
    moves: list[history.SuspiciousMove]


def holding_detail(
    db: Session, portfolio_id: uuid.UUID, user_id: uuid.UUID, symbol: str
) -> HoldingDetail:
    book = _book(db, portfolio_id, user_id)
    view = summary(db, book.id, user_id)
    holding = next((h for h in view.holdings if h.symbol.upper() == symbol.upper()), None)
    if holding is None:
        raise NotFound(f"holding {symbol}")

    pos = pf.position(db, book.id, holding.instrument_id)
    assert pos is not None  # summary listed it, so the fold produced it
    periods = taxrules.holding_periods(pos.lots, pos.asset_class)

    lots = [
        LotView(
            trade_date=hp.lot.trade_date,
            quantity=hp.lot.quantity,
            unit_cost=hp.lot.unit_cost,
            fx_rate_inr=hp.lot.fx_rate_inr,
            cost_inr=hp.lot.quantity * hp.lot.unit_cost * hp.lot.fx_rate_inr,
            days_held=hp.days_held,
            long_term_on=hp.long_term_on,
            is_long_term=hp.is_long_term,
            days_remaining=hp.days_remaining,
        )
        for hp in periods
        if hp.lot.quantity > ZERO
    ]

    transactions = [
        t
        for t in db.execute(
            sa.select(Transaction)
            .where(
                Transaction.portfolio_id == book.id,
                Transaction.instrument_id == holding.instrument_id,
            )
            .order_by(Transaction.trade_date.desc(), Transaction.created_at.desc())
        ).scalars()
    ]
    observations = list(
        db.execute(
            sa.select(PriceObservation)
            .where(PriceObservation.instrument_id == holding.instrument_id)
            .order_by(PriceObservation.observed_at.desc())
            .limit(50)
        ).scalars()
    )
    moves = [
        m for m in history.suspicious_moves(db, book.id) if m.instrument_id == holding.instrument_id
    ]

    return HoldingDetail(
        holding=holding,
        lots=lots,
        if_sold_now=_if_sold_now(pos, holding),
        currency_split=_currency_split(pos, holding),
        transactions=transactions,
        observations=observations,
        moves=moves,
    )


def _if_sold_now(pos: pf.Position, holding: Holding) -> IfSoldNow | None:
    if holding.mark is None or pos.quantity <= ZERO:
        return None
    fx = pos.lots[0].fx_rate_inr if pos.lots and pos.currency != "INR" else Decimal(1)
    if pos.currency != "INR" and holding.market_value_inr is not None and pos.quantity:
        # The rate actually used to value it, so the two bases are compared on one rate.
        fx = holding.market_value_inr / (pos.quantity * holding.mark.price)

    matched = taxrules.match_fifo(
        pos.lots, pos.quantity, holding.mark.price, fx, pos.asset_class, dt.date.today()
    )
    long_term = sum((m.proceeds_inr - m.cost_inr for m in matched if m.is_long_term), ZERO)
    short_term = sum((m.proceeds_inr - m.cost_inr for m in matched if not m.is_long_term), ZERO)
    weighted = taxrules.match_weighted_average(pos.lots, pos.quantity, holding.mark.price, fx)
    return IfSoldNow(
        at_price=holding.mark.price,
        quantity=pos.quantity,
        realised_inr=long_term + short_term,
        long_term_inr=long_term,
        short_term_inr=short_term,
        weighted_average_realised_inr=weighted,
        bases_agree=(long_term + short_term) == weighted,
    )


def _currency_split(pos: pf.Position, holding: Holding) -> returns.CurrencySplit | None:
    """Asset movement against currency movement — mandatory on any non-INR holding."""
    if pos.currency == "INR" or holding.mark is None or not pos.lots:
        return None
    start_price = pos.average_cost
    start_fx = pos.lots[0].fx_rate_inr
    if not start_price or not start_fx or holding.market_value_inr is None:
        return None
    end_fx = holding.market_value_inr / (pos.quantity * holding.mark.price)
    return returns.decompose(
        start_price=start_price,
        end_price=holding.mark.price,
        start_fx=start_fx,
        end_fx=end_fx,
    )
