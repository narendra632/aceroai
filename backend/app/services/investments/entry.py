"""The one write path into the ledger.

`record()` is called by the REST endpoint **and** by the assistant tool. Convention 2, and the
reason it exists: a validation living in only one of them is a validation the other can skip.

⚠ **This function accepts structured data and never prose.** Turning "bought 4 HDFC Bank at
722.65 today" into fields is the *tool's* job, and the tool shows its interpretation back for
confirmation before calling this. A model that can write directly to the ledger is a model
that can invent a holding — and D1 of the whole module exists to stop exactly that.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Instrument, Portfolio, Transaction
from app.services.errors import Invalid, NotFound
from app.services.investments import costmodel
from app.services.investments.portfolio import ACQUIRING, DISPOSING, QUANTITY_ONLY, live, position

#: Which venue's charges apply to which asset class.
VENUE_FOR = {
    "EQUITY_IN": "GROWW_EQUITY",
    "MF_IN": "GROWW_MF",
    "CRYPTO": "COINSWITCH",
    "EQUITY_US": "INDMONEY_US",
}


@dataclass(frozen=True)
class Draft:
    """A transaction as understood, before it is written.

    Returned to the caller so a person can confirm it. The assistant shows this and waits;
    the API returns it from a dry run. Same object, same validation, one code path.
    """

    instrument_symbol: str
    instrument_name: str
    exchange: str
    asset_class: str
    txn_type: str
    trade_date: dt.date
    quantity: Decimal
    price: Decimal
    currency: str
    fx_rate_inr: Decimal
    charges_inr: Decimal
    prepaid_tax_inr: Decimal
    gross_inr: Decimal
    net_inr: Decimal
    warnings: list[str]
    creates_instrument: bool

    def as_dict(self) -> dict:
        return {
            "symbol": self.instrument_symbol,
            "name": self.instrument_name,
            "exchange": self.exchange,
            "action": self.txn_type,
            "date": self.trade_date.isoformat(),
            "quantity": str(self.quantity),
            "price": str(self.price),
            "currency": self.currency,
            "charges_inr": str(self.charges_inr),
            "prepaid_tax_inr": str(self.prepaid_tax_inr),
            "net_inr": str(self.net_inr),
            "warnings": self.warnings,
            "new_instrument": self.creates_instrument,
        }


def find_instrument(db: Session, symbol: str, exchange: str | None = None) -> Instrument | None:
    """Resolve a symbol, including through a rename.

    Aliases matter: HDFC Mid-Cap Opportunities Fund became HDFC Mid Cap Fund under SEBI's
    naming standardisation, same ISIN. Without matching both, a lookup appears to break.
    """
    stmt = sa.select(Instrument).where(
        Instrument.deleted_at.is_(None),
        sa.or_(
            sa.func.upper(Instrument.symbol) == symbol.upper(),
            Instrument.aliases.any(symbol),
        ),
    )
    if exchange:
        stmt = stmt.where(Instrument.exchange == exchange)
    return db.execute(stmt.limit(1)).scalar_one_or_none()


def prepare(
    db: Session,
    portfolio_id: uuid.UUID,
    *,
    symbol: str,
    txn_type: str,
    quantity: Decimal,
    price: Decimal,
    trade_date: dt.date,
    exchange: str | None = None,
    name: str | None = None,
    asset_class: str | None = None,
    currency: str | None = None,
    fx_rate_inr: Decimal | None = None,
) -> Draft:
    """Validate and cost a transaction without writing it. Raises `Invalid` on anything wrong.

    Separated from `record` so the same checks run whether the caller is going to confirm
    with a person or not — there is no "quick path" that skips validation.
    """
    if quantity <= 0:
        raise Invalid("quantity must be positive; a sale is a SELL, not a negative buy")
    if price < 0:
        raise Invalid("price cannot be negative")
    if trade_date > dt.date.today():
        raise Invalid(f"{trade_date} is in the future — the ledger records what happened")

    book = db.get(Portfolio, portfolio_id)
    if book is None or book.deleted_at is not None:
        raise NotFound("portfolio")

    warnings: list[str] = []
    inst = find_instrument(db, symbol, exchange)
    creates = inst is None
    if inst is None:
        if not (exchange and asset_class and currency):
            raise Invalid(
                f"{symbol} is new, so it needs an exchange, asset class and currency "
                "before it can be recorded"
            )
        inst = Instrument(
            id=uuid.uuid4(),
            symbol=symbol.upper(),
            exchange=exchange,
            name=name or symbol.upper(),
            asset_class=asset_class,
            currency=currency,
        )
        warnings.append(f"{symbol.upper()} is new — recording it also starts tracking it")

    fx = fx_rate_inr or (Decimal(1) if inst.currency == "INR" else None)
    if fx is None:
        raise Invalid(
            f"{inst.symbol} is priced in {inst.currency}, so the rupee rate you actually "
            "received is needed — it is a fact about that moment and cannot be looked up later"
        )

    if txn_type in DISPOSING:
        held = position(db, portfolio_id, inst.id)
        if held is None or held.quantity < quantity:
            have = held.quantity if held else Decimal(0)
            raise Invalid(f"cannot sell {quantity} of {inst.symbol}; the book holds {have}")

    charges, prepaid, notes = _cost(db, inst, txn_type, quantity, price, fx, trade_date)
    warnings.extend(notes)

    gross_inr = quantity * price * fx
    net = gross_inr + charges if txn_type in ACQUIRING else gross_inr - charges

    return Draft(
        instrument_symbol=inst.symbol,
        instrument_name=inst.name,
        exchange=inst.exchange,
        asset_class=inst.asset_class,
        txn_type=txn_type,
        trade_date=trade_date,
        quantity=quantity,
        price=price,
        currency=inst.currency,
        fx_rate_inr=fx,
        charges_inr=charges,
        prepaid_tax_inr=prepaid,
        gross_inr=gross_inr,
        net_inr=net,
        warnings=warnings,
        creates_instrument=creates,
    )


def _cost(
    db: Session,
    inst: Instrument,
    txn_type: str,
    quantity: Decimal,
    price: Decimal,
    fx: Decimal,
    trade_date: dt.date,
) -> tuple[Decimal, Decimal, list[str]]:
    """Charges for this transaction, from the schedule in force on its trade date."""
    venue = VENUE_FOR.get(inst.asset_class)
    if venue is None or txn_type not in (ACQUIRING | DISPOSING):
        return Decimal(0), Decimal(0), []

    schedule = costmodel.schedule_for(db, venue, trade_date)
    spec = schedule.spec if schedule else costmodel.DEFAULT_SCHEDULES[venue]
    turnover = quantity * price * fx
    side = "BUY" if txn_type in ACQUIRING else "SELL"

    if venue == "GROWW_EQUITY":
        c = costmodel.equity_charges(turnover, side, spec, exchange=inst.exchange)
    elif venue == "GROWW_MF":
        c = costmodel.mutual_fund_charges(turnover, side, spec, held_in_demat=True)
    elif venue == "COINSWITCH":
        c = costmodel.crypto_charges(turnover, side, spec, fy_sold=Decimal(0))
    else:
        c = costmodel.us_equity_charges(quantity * price, spec)
        # Brokerage is quoted in USD for a US trade; the ledger keeps charges in rupees.
        return (c.total * fx).quantize(Decimal("0.01")), Decimal(0), c.notes

    return c.total, c.prepaid_tax, c.notes


def record(
    db: Session, portfolio_id: uuid.UUID, draft: Draft, *, entry_source: str = "CHAT"
) -> Transaction:
    """Write a confirmed draft. The only function in this codebase that appends to the ledger."""
    inst = find_instrument(db, draft.instrument_symbol, draft.exchange)
    if inst is None:
        inst = Instrument(
            id=uuid.uuid4(),
            symbol=draft.instrument_symbol,
            exchange=draft.exchange,
            name=draft.instrument_name,
            asset_class=draft.asset_class,
            currency=draft.currency,
        )
        db.add(inst)
        db.flush()

    schedule = costmodel.schedule_for(db, VENUE_FOR.get(inst.asset_class, ""), draft.trade_date)
    txn = Transaction(
        id=uuid.uuid4(),
        portfolio_id=portfolio_id,
        instrument_id=inst.id,
        txn_type=draft.txn_type,
        trade_date=draft.trade_date,
        quantity=draft.quantity,
        price=draft.price,
        currency=draft.currency,
        fx_rate_inr=draft.fx_rate_inr,
        charges_inr=draft.charges_inr,
        prepaid_tax_inr=draft.prepaid_tax_inr,
        charge_schedule_id=schedule.id if schedule else None,
        entry_source=entry_source,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def record_action(
    db: Session,
    portfolio_id: uuid.UUID,
    *,
    instrument: Instrument,
    txn_type: str,
    trade_date: dt.date,
    quantity: Decimal,
    note: str | None = None,
) -> Transaction:
    """Write the quantity change an exchange announced. The second write path, and the last.

    Kept here beside `record` rather than in `corpactions` so that every append to the ledger
    is still in one module — a second writer somewhere else is how a rule like "charges are
    computed server-side" ends up applying to only some rows.

    ⚠ It differs from `record` in what it is allowed to do, and each difference is deliberate:

    * **Quantity may be negative.** A consolidation removes units. `prepare` refuses that,
      correctly, because a person typing a negative quantity has made a mistake.
    * **Price is zero, and that is not a missing value.** A bonus hands over units for no
      money. `portfolio.QUANTITY_ONLY` never reads the price; writing the market price here
      would put a number in the record that nothing uses and everything could misread.
    * **No charges and no schedule.** Nothing was traded, so nothing was charged.
    * **`fx_rate_inr` is 1 even on a foreign holding**, because no money moved for it to be a
      rate of. The fold ignores it for these types; it is here because the column is NOT NULL.
    """
    if quantity == 0:
        raise Invalid("a corporate action that changes nothing is not recorded")
    if txn_type not in QUANTITY_ONLY:
        raise Invalid(f"{txn_type} is not a quantity-only event")

    txn = Transaction(
        id=uuid.uuid4(),
        portfolio_id=portfolio_id,
        instrument_id=instrument.id,
        txn_type=txn_type,
        trade_date=trade_date,
        quantity=quantity,
        price=Decimal(0),
        currency=instrument.currency,
        fx_rate_inr=Decimal(1),
        charges_inr=Decimal(0),
        prepaid_tax_inr=Decimal(0),
        entry_source="CORP_ACTION",
        note=note,
    )
    db.add(txn)
    db.flush()
    return txn


def record_paper(
    db: Session,
    portfolio_id: uuid.UUID,
    *,
    instrument: Instrument,
    trade_date: dt.date,
    quantity: Decimal,
    price: Decimal,
    fx_rate_inr: Decimal | None = None,
    note: str | None = None,
) -> Transaction:
    """Write a fill into a PAPER book — what the system's own decisions would have produced.

    The third write path, and the last. Kept here beside `record` and `record_action` so every
    append to any ledger is still in one module.

    ⚠ **Charges are modelled, not skipped.** A paper book that ignores the transaction taxes,
    exchange fees, stamp duty and depository charges flatters itself by a few tenths of a
    percent on every round trip — and the entire purpose of these books is to be compared
    against a real one that pays them.

    ⚠ It does not commit. Unlike `record`, this runs inside a decision that is also writing
    the decision row and arming the conditions, and those must land together or not at all.
    """
    if quantity <= 0:
        raise Invalid("a paper fill needs a positive quantity")

    fx = fx_rate_inr or (Decimal(1) if instrument.currency == "INR" else None)
    if fx is None:
        raise Invalid(f"{instrument.symbol} is priced in {instrument.currency}; a rate is needed")

    charges, prepaid, _ = _cost(db, instrument, "BUY", quantity, price, fx, trade_date)
    schedule = costmodel.schedule_for(db, VENUE_FOR.get(instrument.asset_class, ""), trade_date)
    txn = Transaction(
        id=uuid.uuid4(),
        portfolio_id=portfolio_id,
        instrument_id=instrument.id,
        txn_type="BUY",
        trade_date=trade_date,
        quantity=quantity,
        price=price,
        currency=instrument.currency,
        fx_rate_inr=fx,
        charges_inr=charges,
        prepaid_tax_inr=prepaid,
        charge_schedule_id=schedule.id if schedule else None,
        entry_source="PROPOSAL_APPROVAL",
        note=note,
    )
    db.add(txn)
    db.flush()
    return txn


def reverse(db: Session, txn_id: uuid.UUID, *, note: str | None = None) -> Transaction:
    """Undo, implemented as the ledger requires: a new entry that supersedes the old one.

    ⚠ This is what the UI's undo gesture calls. The user sees the familiar action; the record
    sees an event, and both rows survive. Nothing anywhere deletes a transaction — the
    database would refuse it.
    """
    original = db.get(Transaction, txn_id)
    if original is None:
        raise NotFound("transaction")

    already = db.execute(
        sa.select(Transaction).where(Transaction.supersedes_id == txn_id).limit(1)
    ).scalar_one_or_none()
    if already is not None:
        raise Invalid("that entry has already been corrected")

    # ONE row: an ADJUSTMENT of zero that supersedes the original. `live()` then drops the
    # original from the fold, and this row contributes nothing — so the position returns
    # exactly to what it was, with both entries still readable in the history.
    #
    # A contra entry (a matching SELL against a mistaken BUY) was the alternative and is
    # wrong here: it would conflate "I typed this wrongly" with "I sold it", inventing a
    # disposal that never happened and a realised gain to go with it.
    reversal = Transaction(
        id=uuid.uuid4(),
        portfolio_id=original.portfolio_id,
        instrument_id=original.instrument_id,
        txn_type="ADJUSTMENT",
        trade_date=original.trade_date,
        quantity=Decimal(0),
        price=Decimal(0),
        currency=original.currency,
        fx_rate_inr=original.fx_rate_inr,
        entry_source=original.entry_source,
        supersedes_id=txn_id,
        note=note or "entry withdrawn",
    )
    db.add(reversal)
    db.commit()
    db.refresh(reversal)
    return reversal


def history(db: Session, portfolio_id: uuid.UUID, limit: int = 200) -> list[Transaction]:
    """Every entry, newest first, INCLUDING superseded ones.

    Superseded rows are shown rather than hidden, marked as such. Hiding them would make the
    history agree with the position and lose the thing the append-only design exists for —
    that a correction is visible as a correction.
    """
    return list(
        db.execute(
            sa.select(Transaction)
            .where(Transaction.portfolio_id == portfolio_id)
            .order_by(Transaction.trade_date.desc(), Transaction.created_at.desc())
            .limit(limit)
        ).scalars()
    )


def superseded_ids(db: Session, portfolio_id: uuid.UUID) -> set[uuid.UUID]:
    """Which entries in a book have been corrected, so the UI can mark them."""
    rows = db.execute(
        sa.select(Transaction.supersedes_id).where(
            Transaction.portfolio_id == portfolio_id, Transaction.supersedes_id.isnot(None)
        )
    ).scalars()
    return {r for r in rows if r is not None}


__all__ = [
    "Draft",
    "find_instrument",
    "history",
    "live",
    "prepare",
    "record",
    "record_action",
    "record_paper",
    "reverse",
    "superseded_ids",
]
