"""Splits and bonuses: recorded when announced, applied on their ex-date.

A share-changing action hands you more units for the same money. The exchange quotes the
price after the change and the ledger still holds the count from before it, so for as long as
the two disagree the page reports a loss that did not happen — a 1:1 bonus reads as −50%.
It is the highest-damage failure mode in this module, because the number is large, alarming,
and the obvious reaction to it is to sell something that did nothing wrong.

Three rules shape everything here.

**Nothing is guessed.** A ratio is parsed only from a form that cannot mean two things. NSE's
free text says `BONUS 1:1` unambiguously, and `SPLIT FROM RS.10/- TO RE.1/-` unambiguously —
but a bare `SPLIT 1:10` does not say which side is which, and a holding multiplied the wrong
way is a fiction ten times the size of the one being fixed. Anything unparsed is stored as
`NEEDS_REVIEW`, which flags the holding and waits for a person. Refusing to answer is a
supported outcome.

**Total cost basis is conserved.** More units, same money: only the per-unit cost falls. This
is what `portfolio.QUANTITY_ONLY` implements, and it is why the applied transaction carries a
price of zero rather than a value.

**Applying is reversible, and visible.** The applied row is an ordinary ledger entry with
`entry_source='CORP_ACTION'`, so it shows in the history, and the existing correction path
retires it if the exchange or the match was wrong.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import CorporateAction, Instrument, Transaction
from app.services.errors import Invalid, NotFound
from app.services.investments import portfolio as pf

ZERO = Decimal(0)

#: Statuses where the action is still outstanding, so the holding's P&L cannot be trusted.
#: This is gate G7 of the build spec, in the one place both the page and the assistant read.
OPEN = ("PENDING", "NEEDS_REVIEW")

#: How far a multiplier may stray before it is treated as a misreading rather than an action.
#: A 1:20 bonus and a ₹100→₹1 split both exist; a multiplier of 500 is a parse gone wrong, and
#: applying it would replace a frightening wrong number with a preposterous one.
MIN_MULTIPLIER, MAX_MULTIPLIER = Fraction(1, 50), Fraction(50, 1)

#: `BONUS 1:1`, `BONUS ISSUE 2:1`, `BONUS 1 : 1`. The count between is bounded so that two
#: unrelated numbers elsewhere in a long string cannot be read as a ratio.
_BONUS_RATIO = re.compile(r"BONUS\D{0,30}?(\d{1,3})\s*[:/]\s*(\d{1,3})", re.IGNORECASE)

#: `FACE VALUE SPLIT FROM RS.10/- TO RE.1/-`, `SUB-DIVISION ... FROM RS 10 TO RS 2`.
#: ⚠ Face values only. A bare `SPLIT 1:10` does not say which side is the old value, and
#: guessing wrong multiplies the holding by 100 in the wrong direction.
_SPLIT_FACES = re.compile(
    r"(?:SPLIT|SUB[\s-]?DIVISION|CONSOLIDAT\w*)"
    r".{0,60}?R[SE]\.?\s*(\d{1,5}(?:\.\d{1,2})?)"
    r".{0,20}?R[SE]\.?\s*(\d{1,5}(?:\.\d{1,2})?)",
    re.IGNORECASE | re.DOTALL,
)

_IS_BONUS = re.compile(r"\bBONUS\b", re.IGNORECASE)
_IS_SPLIT = re.compile(r"SPLIT|SUB[\s-]?DIVISION|CONSOLIDAT", re.IGNORECASE)


@dataclass(frozen=True)
class Parsed:
    """What a feed string was understood to mean, or why it was not."""

    action_type: str
    ratio: Fraction | None
    #: Present exactly when `ratio` is None — the sentence a person reads before deciding.
    unparsed_because: str | None = None


def classify(purpose: str) -> str | None:
    """`BONUS`, `SPLIT`, or None when the text changes no share count.

    A consolidation is a split with a multiplier below one, and is deliberately not a fourth
    vocabulary word: it does the same thing to the ledger in the other direction.
    """
    bonus, split = bool(_IS_BONUS.search(purpose)), bool(_IS_SPLIT.search(purpose))
    if bonus and split:
        # One announcement carrying both is real and rare. It is not parsed, because the
        # order the two compose in is not stated and the two orders give different answers.
        return "BONUS"
    if bonus:
        return "BONUS"
    if split:
        return "SPLIT"
    return None


def parse(purpose: str) -> Parsed | None:
    """Read an announcement. None when it changes no share count.

    The returned `ratio` is the **multiplier**: what to multiply the held quantity by. A 1:1
    bonus is 2, a ₹10→₹1 split is 10, a 10→1 consolidation is 1/10.
    """
    action_type = classify(purpose)
    if action_type is None:
        return None

    if _IS_BONUS.search(purpose) and _IS_SPLIT.search(purpose):
        return Parsed(
            action_type,
            None,
            "it announces a bonus and a split together, and the order they apply in is not stated",
        )

    if action_type == "BONUS":
        match = _BONUS_RATIO.search(purpose)
        if match is None:
            return Parsed(action_type, None, "no bonus ratio in the announcement")
        new, held = int(match.group(1)), int(match.group(2))
        if not held:
            return Parsed(action_type, None, "the bonus ratio divides by zero")
        # "a:b" means a new shares for every b held — so b becomes a + b.
        ratio = Fraction(new + held, held)
    else:
        match = _SPLIT_FACES.search(purpose)
        if match is None:
            return Parsed(
                action_type,
                None,
                "the announcement gives no face values, and a bare ratio does not say "
                "which side is the old one",
            )
        old = Fraction(match.group(1)).limit_denominator(100)
        new = Fraction(match.group(2)).limit_denominator(100)
        if not new or not old:
            return Parsed(action_type, None, "a face value in the announcement is zero")
        ratio = old / new

    if ratio == 1:
        return Parsed(action_type, None, "the announcement leaves the share count unchanged")
    if not MIN_MULTIPLIER <= ratio <= MAX_MULTIPLIER:
        return Parsed(action_type, None, f"the implied change ({ratio}×) is too large to believe")
    return Parsed(action_type, ratio)


def multiplier(action: CorporateAction) -> Fraction | None:
    """The stored ratio, or None when it was never parsed."""
    if action.ratio_num is None or action.ratio_den is None:
        return None
    return Fraction(action.ratio_num, action.ratio_den)


def _dedupe_key(action_type: str, ex_date: dt.date | None, purpose: str) -> str:
    """One announcement, one row, however many evenings it stays in the feed.

    Keyed on the normalised text rather than on the date alone, because NSE re-announces a
    corrected ex-date as a separate item and that genuinely is a different fact.
    """
    flattened = re.sub(r"\s+", " ", purpose.strip().upper())
    return f"{action_type}|{ex_date.isoformat() if ex_date else 'undated'}|{flattened}"


def ingest(
    db: Session,
    found: list[tuple[Instrument, object]],
    *,
    source: str = "NSE",
    announced_at: dt.datetime | None = None,
) -> list[CorporateAction]:
    """Record announcements that are not recorded yet. Returns only the new rows.

    `found` is what `marketdata.feed.share_changing_actions` returns: pairs of the held
    instrument and the feed item that matched it. Nothing here re-checks the match — that
    rule lives in the adapter, and having it in two places is having it in neither.
    """
    announced_at = announced_at or dt.datetime.now(dt.UTC)
    fresh: list[CorporateAction] = []

    for instrument, item in found:
        purpose = (getattr(item, "purpose", "") or "").strip()
        ex_date = getattr(item, "ex_date", None)
        parsed = parse(purpose)
        if parsed is None:
            continue

        key = _dedupe_key(parsed.action_type, ex_date, purpose)
        existing = db.execute(
            sa.select(CorporateAction.id).where(
                CorporateAction.instrument_id == instrument.id,
                CorporateAction.dedupe_key == key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        row = CorporateAction(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            action_type=parsed.action_type,
            ex_date=ex_date,
            ratio_num=parsed.ratio.numerator if parsed.ratio else None,
            ratio_den=parsed.ratio.denominator if parsed.ratio else None,
            announced_at=announced_at,
            source=source,
            purpose=purpose,
            dedupe_key=key,
            status="PENDING" if parsed.ratio else "NEEDS_REVIEW",
            note=parsed.unparsed_because,
        )
        db.add(row)
        fresh.append(row)

    if fresh:
        db.flush()
    return fresh


def due(db: Session, *, today: dt.date | None = None) -> list[CorporateAction]:
    """Parsed actions whose ex-date has arrived and which have not been applied.

    ⚠ Dated actions only. An announcement with no ex-date is never applied on a schedule: the
    day a quantity changes is a fact, and applying one on the day it was *read* would put the
    change on the wrong date and silently distort every figure derived from the ledger's dates.
    """
    today = today or dt.date.today()
    return list(
        db.execute(
            sa.select(CorporateAction)
            .where(
                CorporateAction.status == "PENDING",
                CorporateAction.ex_date.isnot(None),
                CorporateAction.ex_date <= today,
                CorporateAction.ratio_num.isnot(None),
            )
            .order_by(CorporateAction.ex_date)
        ).scalars()
    )


def open_actions(db: Session, instrument_ids: list[uuid.UUID]) -> dict[uuid.UUID, CorporateAction]:
    """The outstanding action per instrument — gate G7, in one place.

    While one of these exists the holding's profit and loss is arithmetic over two counts that
    disagree, and every reader must say so rather than present the figure.
    """
    if not instrument_ids:
        return {}
    rows = db.execute(
        sa.select(CorporateAction)
        .where(
            CorporateAction.instrument_id.in_(instrument_ids),
            CorporateAction.status.in_(OPEN),
        )
        .order_by(CorporateAction.ex_date.desc().nullslast(), CorporateAction.announced_at.desc())
    ).scalars()
    out: dict[uuid.UUID, CorporateAction] = {}
    for row in rows:
        out.setdefault(row.instrument_id, row)
    return out


def quantity_change(
    db: Session, portfolio_id: uuid.UUID, action: CorporateAction
) -> Decimal | None:
    """How many units this action adds — negative for a consolidation. None when it cannot.

    Computed rather than stored, and shown before applying, so what is about to happen to the
    holding is a number a person can check against their broker.
    """
    ratio = multiplier(action)
    if ratio is None:
        return None
    held = pf.position(db, portfolio_id, action.instrument_id)
    if held is None or held.quantity <= ZERO:
        return None
    after = (held.quantity * ratio.numerator) / ratio.denominator
    # Eight decimals is the ledger's own precision. A ratio that does not divide the holding
    # evenly leaves a fractional unit, which is what the exchange pays out in cash — a
    # rounding the user records as they see it rather than one invented here.
    return (after - held.quantity).quantize(Decimal("0.00000001"))


def apply(
    db: Session,
    portfolio_id: uuid.UUID,
    action: CorporateAction,
    *,
    at: dt.datetime | None = None,
) -> Transaction | None:
    """Write the quantity change into the ledger and close the action.

    Returns the transaction, or None when there was nothing to do — in which case the action
    is marked IGNORED with the reason, because "nothing was held" is an answer and leaving the
    row PENDING would flag the holding forever.
    """
    from app.services.investments import entry

    if action.status not in OPEN:
        raise Invalid(f"that action is already {action.status.lower()}")
    ratio = multiplier(action)
    if ratio is None:
        raise Invalid(
            "the ratio in that announcement was never understood, so there is no quantity "
            "to apply — record the change yourself and dismiss this"
        )

    delta = quantity_change(db, portfolio_id, action)
    if delta is None or delta == ZERO:
        action.status = "IGNORED"
        action.note = "nothing of this holding was held when the action fell due"
        db.flush()
        return None

    instrument = db.get(Instrument, action.instrument_id)
    if instrument is None:
        raise NotFound("instrument")

    txn = entry.record_action(
        db,
        portfolio_id,
        instrument=instrument,
        txn_type=action.action_type,
        trade_date=action.ex_date or dt.date.today(),
        quantity=delta,
        note=f"{action.source}: {action.purpose}",
    )
    action.status = "APPLIED"
    action.applied_at = at or dt.datetime.now(dt.UTC)
    action.applied_txn_id = txn.id
    db.flush()
    return txn


def dismiss(db: Session, action: CorporateAction, *, note: str | None = None) -> CorporateAction:
    """Mark an action as not applying to this book, clearing the holding's flag."""
    if action.status == "APPLIED":
        raise Invalid(
            "that action has already been applied — correct the transaction it wrote instead"
        )
    action.status = "IGNORED"
    action.note = note or "dismissed"
    db.flush()
    return action


def listing(db: Session, *, since_days: int = 120) -> list[CorporateAction]:
    """Everything outstanding, plus what was recently applied so it can be checked."""
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=since_days)
    return list(
        db.execute(
            sa.select(CorporateAction)
            .where(
                sa.or_(
                    CorporateAction.status.in_(OPEN),
                    CorporateAction.announced_at >= cutoff,
                )
            )
            .order_by(CorporateAction.announced_at.desc())
        ).scalars()
    )


def ratio_text(action: CorporateAction) -> str | None:
    """`1:1 bonus`, `10 shares for every 1`, or None when nothing was parsed."""
    ratio = multiplier(action)
    if ratio is None:
        return None
    if action.action_type == "BONUS":
        # The stored multiplier is (new + held) / held; the announced ratio is new : held.
        return f"{ratio.numerator - ratio.denominator}:{ratio.denominator} bonus"
    if ratio > 1:
        return f"{ratio.numerator}-for-{ratio.denominator} split"
    return f"{ratio.denominator}-into-{ratio.numerator} consolidation"


@dataclass(frozen=True)
class ActionView:
    """One action as the page and the assistant both need it.

    A flat shape rather than the ORM row because two of these fields are computed — what the
    ratio means in words, and how many units it would add to *this* book. Computing them in
    the interface would put the arithmetic that changes a holding's quantity in the browser.
    """

    id: uuid.UUID
    instrument_id: uuid.UUID
    symbol: str
    name: str
    action_type: str
    ex_date: dt.date | None
    purpose: str
    status: str
    source: str
    announced_at: dt.datetime
    applied_at: dt.datetime | None
    note: str | None
    ratio_text: str | None
    #: Units this would add, negative for a consolidation. None when the ratio was never
    #: parsed, or when nothing of the holding is held.
    quantity_change: Decimal | None
    quantity_before: Decimal | None
    quantity_after: Decimal | None


def view(db: Session, portfolio_id: uuid.UUID, action: CorporateAction) -> ActionView:
    instrument = db.get(Instrument, action.instrument_id)
    held = pf.position(db, portfolio_id, action.instrument_id)
    before = held.quantity if held and held.quantity > ZERO else None
    # ⚠ Only meaningful while the action is outstanding. Once APPLIED the change is already
    # in the ledger, so recomputing it against the new quantity would describe a second one.
    change = quantity_change(db, portfolio_id, action) if action.status in OPEN else None
    return ActionView(
        id=action.id,
        instrument_id=action.instrument_id,
        symbol=instrument.symbol if instrument else "?",
        name=instrument.name if instrument else "?",
        action_type=action.action_type,
        ex_date=action.ex_date,
        purpose=action.purpose,
        status=action.status,
        source=action.source,
        announced_at=action.announced_at,
        applied_at=action.applied_at,
        note=action.note,
        ratio_text=ratio_text(action),
        quantity_change=change,
        quantity_before=before,
        quantity_after=(before + change) if (before is not None and change is not None) else None,
    )


def views(db: Session, portfolio_id: uuid.UUID, actions: list[CorporateAction]) -> list[ActionView]:
    return [view(db, portfolio_id, a) for a in actions]
