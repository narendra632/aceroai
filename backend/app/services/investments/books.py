"""The books, side by side — and what the difference between them measures.

Six ledgers, and the whole point is that **none of them is a subset of another**. Three
categories exist and a single combined book would silently discard the third:

* Acero proposed → you approved → you did it
* Acero proposed → you approved → you did something else
* **you bought something Acero never proposed**

That third group is the direct measurement of your unaided judgement against the machine's,
and it only exists because the real book and the paper books are kept apart.

⚠ **Read in aggregate, on a schedule — never after a name that got away.** A rejected idea
that rose is far more memorable than one that fell, and a what-if ledger browsed casually
trains worse judgement rather than better. That is not a warning about the data; it is a
warning about the reader, and it applies to whoever built it too.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Instrument, Portfolio, Proposal, ShadowEntry, Transaction
from app.services.investments import portfolio as pf
from app.services.investments import pricing

ZERO = Decimal(0)

#: What each book is for, in the words the interface uses.
BOOKS: dict[str, tuple[str, str]] = {
    "REAL": ("What I actually hold", "your word, never written by a machine"),
    "MIRROR": (
        "If I had followed Acero",
        "your holdings at the moment this started, plus every suggestion you approved",
    ),
    "AI_CLEAN": (
        "What Acero itself produced",
        "from nothing, only the suggestions you approved — the clean measure of the machine",
    ),
    "PROPOSED_ALL": (
        "Everything it ever suggested",
        "equally weighted, never sold. If the real book cannot beat this, the picking works "
        "and the acting does not",
    ),
    "SHADOW_VETO": ("What I turned down", "the cost of your vetoes"),
    "SHADOW_BUDGET": ("What the budget could not fund", "the cost of the constraint"),
    "SHADOW_GATE": (
        "What the rules blocked",
        "the cost of the rails — the only way to find out whether they protect or obstruct",
    ),
}

#: The notional put into each idea in the "everything it ever suggested" benchmark.
#: ⚠ Equal weighting is the point: the benchmark asks whether the IDEAS were good, and
#: sizing them by conviction would fold the sizing judgement back into the answer.
BENCHMARK_TICKET = Decimal(10000)


def get(db: Session, user_id: uuid.UUID, kind: str) -> Portfolio | None:
    return db.execute(
        sa.select(Portfolio).where(
            Portfolio.user_id == user_id,
            Portfolio.kind == kind,
            Portfolio.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


def ensure(db: Session, user_id: uuid.UUID, kind: str) -> Portfolio:
    found = get(db, user_id, kind)
    if found is not None:
        return found
    name, _ = BOOKS.get(kind, (kind, ""))
    found = Portfolio(id=uuid.uuid4(), user_id=user_id, name=name, kind=kind)
    db.add(found)
    db.flush()
    return found


def seed_mirror(db: Session, user_id: uuid.UUID) -> int:
    """Copy the real book's transactions into `MIRROR`, once.

    ⚠ Copied rather than referenced, and only if `MIRROR` is empty. The book means "what my
    portfolio would look like if I had followed Acero **from here**", so it takes a snapshot
    of where "here" was and then diverges. Re-seeding later, or keeping it in step with new
    real transactions, would quietly change what the comparison is measuring — from "did
    following Acero help" to "does Acero agree with what I did anyway".

    Returns how many entries were copied. Zero on every run after the first.
    """
    mirror = ensure(db, user_id, "MIRROR")
    already = db.execute(
        sa.select(sa.func.count())
        .select_from(Transaction)
        .where(Transaction.portfolio_id == mirror.id)
    ).scalar_one()
    if already:
        return 0

    real = get(db, user_id, "REAL")
    if real is None:
        return 0

    copied = 0
    for txn in pf.ledger(db, real.id):
        db.add(
            Transaction(
                id=uuid.uuid4(),
                portfolio_id=mirror.id,
                instrument_id=txn.instrument_id,
                txn_type=txn.txn_type,
                trade_date=txn.trade_date,
                quantity=txn.quantity,
                price=txn.price,
                currency=txn.currency,
                fx_rate_inr=txn.fx_rate_inr,
                charges_inr=txn.charges_inr,
                prepaid_tax_inr=txn.prepaid_tax_inr,
                entry_source="IMPORT",
                note="opening position, copied from the real book when this book was started",
            )
        )
        copied += 1
    db.flush()
    return copied


@dataclass(frozen=True)
class Line:
    """One book or benchmark, valued."""

    kind: str
    name: str
    purpose: str
    invested_inr: Decimal
    value_inr: Decimal | None
    positions: int
    #: ⚠ None when even one holding lacks a price. A total assembled from partial coverage
    #: steps whenever COVERAGE changes, and a reader cannot tell that from a real movement.
    is_complete: bool

    @property
    def gain_inr(self) -> Decimal | None:
        return None if self.value_inr is None else self.value_inr - self.invested_inr

    @property
    def gain_pct(self) -> Decimal | None:
        if self.value_inr is None or not self.invested_inr:
            return None
        return (self.value_inr - self.invested_inr) / self.invested_inr


def _value_book(db: Session, book: Portfolio) -> Line:
    positions = pf.positions(db, book.id)
    name, purpose = BOOKS.get(book.kind, (book.name, ""))
    if not positions:
        return Line(book.kind, name, purpose, ZERO, ZERO, 0, True)

    marks = pricing.latest(db, [p.instrument_id for p in positions])
    valued = pricing.value(positions, marks, pricing.latest_fx(db))
    invested = sum((v.cost_basis_inr for v in valued), ZERO)
    priced = [v for v in valued if v.is_priced]
    complete = len(priced) == len(valued)
    return Line(
        kind=book.kind,
        name=name,
        purpose=purpose,
        invested_inr=invested,
        value_inr=sum((v.market_value_inr for v in priced), ZERO) if complete else None,
        positions=len(valued),
        is_complete=complete,
    )


def _value_shadow(db: Session, book: Portfolio) -> Line:
    """A what-if book is valued from its entries, which carry no transactions."""
    entries = list(
        db.execute(sa.select(ShadowEntry).where(ShadowEntry.portfolio_id == book.id)).scalars()
    )
    name, purpose = BOOKS.get(book.kind, (book.name, ""))
    if not entries:
        return Line(book.kind, name, purpose, ZERO, ZERO, 0, True)

    instruments = dict(
        db.execute(
            sa.select(Proposal.id, Proposal.instrument_id).where(
                Proposal.id.in_({e.proposal_id for e in entries})
            )
        ).all()
    )
    marks = pricing.latest(db, list({i for i in instruments.values() if i}))

    invested = value = ZERO
    complete = True
    for entry in entries:
        invested += entry.entry_price * entry.quantity
        instrument_id = instruments.get(entry.proposal_id)
        mark = marks.get(instrument_id) if instrument_id else None
        # A position that was exited keeps the price it was closed at; an open one is marked.
        if entry.exit_price is not None:
            value += entry.exit_price * entry.quantity
        elif mark is not None:
            value += mark.price * entry.quantity
        else:
            complete = False
    return Line(
        kind=book.kind,
        name=name,
        purpose=purpose,
        invested_inr=invested,
        value_inr=value if complete else None,
        positions=len(entries),
        is_complete=complete,
    )


def _value_proposed_all(db: Session, user_id: uuid.UUID) -> Line:
    """Buy everything it ever suggested, weight them equally, never sell.

    ⚠ Blocked suggestions are excluded. They were never *proposed* — the rules stopped them
    before they reached anyone — and including them would measure the rules rather than the
    ideas, which is what the shadow book already does separately.
    """
    name, purpose = BOOKS["PROPOSED_ALL"]
    mirror = get(db, user_id, "MIRROR")
    if mirror is None:
        return Line("PROPOSED_ALL", name, purpose, ZERO, ZERO, 0, True)

    rows = list(
        db.execute(
            sa.select(Proposal).where(
                Proposal.portfolio_id == mirror.id,
                Proposal.status == "PENDING",
                Proposal.action.in_(("INITIATE", "ADD", "ACCUMULATE_POOL")),
            )
        ).scalars()
    )
    if not rows:
        return Line("PROPOSED_ALL", name, purpose, ZERO, ZERO, 0, True)

    marks = pricing.latest(db, list({r.instrument_id for r in rows}))
    invested = value = ZERO
    complete = True
    for row in rows:
        raw = (row.price_snapshot or {}).get("price")
        if not raw:
            continue
        entry = Decimal(str(raw))
        if entry <= 0:
            continue
        quantity = BENCHMARK_TICKET / entry
        invested += BENCHMARK_TICKET
        mark = marks.get(row.instrument_id)
        if mark is None:
            complete = False
            continue
        value += mark.price * quantity
    return Line(
        kind="PROPOSED_ALL",
        name=name,
        purpose=purpose,
        invested_inr=invested,
        value_inr=value if complete else None,
        positions=len(rows),
        is_complete=complete,
    )


@dataclass
class Comparison:
    """Every book, valued the same way, so the differences mean something."""

    lines: list[Line] = field(default_factory=list)
    as_of: dt.datetime | None = None

    def by_kind(self, kind: str) -> Line | None:
        return next((line for line in self.lines if line.kind == kind), None)

    @property
    def readable(self) -> bool:
        """⚠ False until the real book and at least one paper book are both fully priced.
        Comparing a complete total with a partial one is worse than not comparing."""
        real = self.by_kind("REAL")
        paper = self.by_kind("AI_CLEAN")
        return bool(real and paper and real.is_complete and paper.is_complete)


def compare(db: Session, user_id: uuid.UUID) -> Comparison:
    """All six books plus the benchmark, valued at the same prices at the same moment.

    ⚠ The same prices, deliberately. Valuing one book at yesterday's close and another at
    today's live price would produce a difference that is entirely an artefact of when each
    was read.
    """
    out = Comparison(as_of=dt.datetime.now(dt.UTC))
    for kind in ("REAL", "MIRROR", "AI_CLEAN"):
        book = get(db, user_id, kind)
        if book is not None:
            out.lines.append(_value_book(db, book))
    out.lines.append(_value_proposed_all(db, user_id))
    for kind in ("SHADOW_VETO", "SHADOW_BUDGET", "SHADOW_GATE"):
        book = get(db, user_id, kind)
        if book is not None:
            out.lines.append(_value_shadow(db, book))
    return out


def unaided(db: Session, user_id: uuid.UUID) -> list[str]:
    """Holdings the system never suggested — the third category, measured.

    ⚠ This is the direct read on your own judgement against the machine's, and it exists only
    because the books are kept apart. A single merged ledger would discard it silently.
    """
    real = get(db, user_id, "REAL")
    mirror = get(db, user_id, "MIRROR")
    if real is None:
        return []
    suggested: set[uuid.UUID] = set()
    if mirror is not None:
        suggested = {
            row
            for row in db.execute(
                sa.select(Proposal.instrument_id).where(Proposal.portfolio_id == mirror.id)
            ).scalars()
        }
    held = pf.positions(db, real.id)
    names = dict(
        db.execute(
            sa.select(Instrument.id, Instrument.symbol).where(
                Instrument.id.in_([p.instrument_id for p in held])
            )
        ).all()
    )
    return sorted(
        names[p.instrument_id]
        for p in held
        if p.instrument_id not in suggested and p.instrument_id in names
    )
