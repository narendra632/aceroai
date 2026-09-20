"""The fold: transactions in, positions out.

Nothing here is stored. `positions()` reads the ledger and computes, every time it is
called, and that is the design rather than an oversight — see the package docstring.

Measured on the real seed (22 transactions): sub-millisecond. At 500 transactions a year it
stays sub-millisecond for years, which is why `daily_valuations` is not in this change.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models import Instrument, Transaction

ZERO = Decimal(0)

#: Types that add units without adding cost. A bonus issue or a split hands you more units
#: for the same money — TOTAL COST BASIS IS CONSERVED and only the per-unit cost falls. Get
#: this wrong and a 1:1 bonus reads as a 50% loss, which is the highest-damage failure mode
#: in the whole module.
QUANTITY_ONLY = frozenset({"BONUS", "SPLIT"})

#: Types that move units in or out at a stated cost.
ACQUIRING = frozenset({"BUY", "SIP", "IPO_ALLOT", "RIGHTS", "TRANSFER_IN"})
DISPOSING = frozenset({"SELL", "TRANSFER_OUT"})

#: Types that touch cash but never units. `TDS` is here rather than in charges because it is
#: withheld tax, not a fee — see `Transaction.prepaid_tax_inr`.
NON_POSITIONAL = frozenset({"DIVIDEND", "FEE", "TDS"})


@dataclass
class Lot:
    """One acquisition, still open. FIFO disposal consumes these in order."""

    txn_id: uuid.UUID
    trade_date: dt.date
    quantity: Decimal
    #: Per unit, in the instrument's own currency, INCLUDING the acquisition's charges.
    unit_cost: Decimal
    fx_rate_inr: Decimal


@dataclass
class Position:
    """What is held in one instrument, and what it cost. All computed, never stored."""

    instrument_id: uuid.UUID
    symbol: str
    asset_class: str
    currency: str
    quantity: Decimal = ZERO
    #: In the instrument's own currency.
    cost_basis: Decimal = ZERO
    #: In INR, at the rates actually paid. Differs from `cost_basis` for non-INR holdings,
    #: and the difference is not a return — see `returns.decompose`.
    cost_basis_inr: Decimal = ZERO
    realised_inr: Decimal = ZERO
    charges_inr: Decimal = ZERO
    prepaid_tax_inr: Decimal = ZERO
    lots: list[Lot] = field(default_factory=list)

    @property
    def average_cost(self) -> Decimal | None:
        """Weighted average, in the instrument's currency. None when nothing is held.

        ⚠ This is the DISPLAY number — what every broker app shows. It is not what tax uses.
        Indian demat disposals are matched FIFO, and on a multi-lot holding the two give
        different realised gains on the same sale. `taxrules` computes the FIFO view, and the
        interface must say which is which rather than quietly picking one.
        """
        return (self.cost_basis / self.quantity) if self.quantity else None

    @property
    def is_open(self) -> bool:
        return self.quantity != ZERO


def live(stmt: Select) -> Select:
    """Restrict a transaction query to entries nothing supersedes.

    The one definition of "still true", mirroring `services.memory.live`. A correction is a
    new row pointing at the one it replaces; both stay in the record, and readers resolve to
    the survivors. Every caller routes through here so no query can forget it.
    """
    superseded = select(Transaction.supersedes_id).where(Transaction.supersedes_id.isnot(None))
    return stmt.where(Transaction.id.notin_(superseded))


def ledger(db: Session, portfolio_id: uuid.UUID) -> Sequence[Transaction]:
    """Every live transaction in a book, oldest first.

    ⚠ Ordered by `(trade_date, created_at, id)`, not by `trade_date` alone. Two lots bought
    the same day is the common case — HDFC Bank has two on 2026-08-12 — and FIFO needs a
    total order or which lot is consumed first becomes arbitrary. That is the same class of
    defect as the untied vector ranking fixed in `05aedb0`, so it is settled here rather
    than discovered later.
    """
    stmt = live(select(Transaction).where(Transaction.portfolio_id == portfolio_id)).order_by(
        Transaction.trade_date, Transaction.created_at, Transaction.id
    )
    return db.execute(stmt).scalars().all()


def _apply(pos: Position, txn: Transaction) -> None:
    """Fold one transaction into a position."""
    qty, price = txn.quantity, txn.price
    fx = txn.fx_rate_inr or Decimal(1)

    pos.charges_inr += txn.charges_inr or ZERO
    pos.prepaid_tax_inr += txn.prepaid_tax_inr or ZERO

    if txn.txn_type in NON_POSITIONAL:
        return

    if txn.txn_type in QUANTITY_ONLY:
        # More units, same money. Every lot grows in the same proportion and its per-unit cost
        # falls by exactly that proportion, so total cost basis is untouched.
        before = pos.quantity
        pos.quantity += qty
        if before:
            _rescale_lots(pos, pos.quantity / before)
        return

    if txn.txn_type in ACQUIRING:
        # Charges belong in the cost of what was acquired: they are money spent to own it.
        charge_per_unit = ((txn.charges_inr or ZERO) / fx / qty) if qty else ZERO
        unit_cost = price + charge_per_unit
        pos.quantity += qty
        pos.cost_basis += unit_cost * qty
        pos.cost_basis_inr += unit_cost * qty * fx
        pos.lots.append(
            Lot(
                txn_id=txn.id,
                trade_date=txn.trade_date,
                quantity=qty,
                unit_cost=unit_cost,
                fx_rate_inr=fx,
            )
        )
        return

    if txn.txn_type in DISPOSING:
        _dispose(pos, qty, price, fx, txn.charges_inr or ZERO)
        return

    if txn.txn_type == "ADJUSTMENT":
        pos.quantity += qty
        pos.cost_basis += price * qty
        pos.cost_basis_inr += price * qty * fx


def _rescale_lots(pos: Position, factor: Decimal) -> None:
    """Restate every lot after a split or bonus: `factor` times as many, each worth that
    much less.

    ⚠ **Per lot, not to a common average.** This used to hand every lot the same unit cost —
    the book's average — which conserved the total and destroyed the thing lots exist for.
    Two lots of HDFC Bank bought at ₹960 and ₹722 are, after a 1:1 bonus, worth ₹480 and ₹361
    a share; flattening both to ₹420 leaves the total right and makes every FIFO disposal
    afterwards report the wrong realised gain, on the one figure the tax view depends on.
    """
    if factor <= ZERO:
        return
    for lot in pos.lots:
        lot.quantity *= factor
        lot.unit_cost /= factor


def _dispose(
    pos: Position, qty: Decimal, price: Decimal, fx: Decimal, charges_inr: Decimal
) -> None:
    """Consume lots FIFO, realising gain against what those specific lots cost.

    FIFO because that is how Indian demat sales are matched, and therefore the only basis on
    which the realised figure means anything for tax. Charges on the sale reduce the gain —
    they are a cost of disposing.
    """
    remaining = qty
    relieved_inr = ZERO
    while remaining > ZERO and pos.lots:
        lot = pos.lots[0]
        take = min(remaining, lot.quantity)
        relieved_inr += take * lot.unit_cost * lot.fx_rate_inr
        pos.cost_basis -= take * lot.unit_cost
        lot.quantity -= take
        remaining -= take
        if lot.quantity <= ZERO:
            pos.lots.pop(0)

    proceeds_inr = qty * price * fx
    pos.realised_inr += proceeds_inr - relieved_inr - charges_inr
    pos.cost_basis_inr -= relieved_inr
    pos.quantity -= qty


def positions(
    db: Session, portfolio_id: uuid.UUID, *, include_closed: bool = False
) -> list[Position]:
    """Every holding in a book, folded from its transactions.

    Closed positions are excluded by default and available on request: a holding sold to zero
    still carries realised gain that a year's review needs, but a holdings table showing rows
    of zero is a holdings table nobody reads.
    """
    txns = ledger(db, portfolio_id)
    if not txns:
        return []

    meta = {
        i.id: i
        for i in db.execute(
            select(Instrument).where(Instrument.id.in_({t.instrument_id for t in txns}))
        ).scalars()
    }

    out: dict[uuid.UUID, Position] = {}
    for txn in txns:
        pos = out.get(txn.instrument_id)
        if pos is None:
            inst = meta[txn.instrument_id]
            pos = Position(
                instrument_id=inst.id,
                symbol=inst.symbol,
                asset_class=inst.asset_class,
                currency=inst.currency,
            )
            out[txn.instrument_id] = pos
        _apply(pos, txn)

    result = list(out.values())
    if not include_closed:
        result = [p for p in result if p.is_open]
    return sorted(result, key=lambda p: p.symbol)


def position(db: Session, portfolio_id: uuid.UUID, instrument_id: uuid.UUID) -> Position | None:
    """One holding, or None if the book has never touched that instrument."""
    for pos in positions(db, portfolio_id, include_closed=True):
        if pos.instrument_id == instrument_id:
            return pos
    return None


def cash_flows(txns: Iterable[Transaction]) -> list[tuple[dt.date, Decimal]]:
    """Signed INR cash flows, for the return calculations.

    Money leaving the investor is negative, money arriving is positive. Charges are part of
    what left; prepaid tax is NOT — it is withheld against a future liability and is
    creditable, so treating it as an outflow would understate the return twice over.
    """
    flows: list[tuple[dt.date, Decimal]] = []
    for txn in txns:
        fx = txn.fx_rate_inr or Decimal(1)
        gross = txn.quantity * txn.price * fx
        charges = txn.charges_inr or ZERO
        if txn.txn_type in ACQUIRING:
            flows.append((txn.trade_date, -(gross + charges)))
        elif txn.txn_type in DISPOSING:
            flows.append((txn.trade_date, gross - charges))
        elif txn.txn_type == "DIVIDEND":
            flows.append((txn.trade_date, gross - charges))
    return flows
