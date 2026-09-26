"""From a score to a suggestion a person can act on — or refuse, on the record.

This is the loop the whole module exists for: read the numbers, apply the rules, write down
what is suggested **and why, before anyone knows how it turns out**, and keep the refusals as
carefully as the suggestions.

⚠ **No model writes anything here.** The thesis, the invalidation conditions and the claims
are all assembled from figures the company filed and rules a person agreed to. That is a
deliberate first version rather than a limitation to apologise for: a thesis built this way
cannot contain a number that was never filed, which is the single failure mode that would make
the whole record worthless. When a model does write the prose, it will be writing *around*
these figures, not producing them.

⚠ **A refusal is written down too.** A blocked proposal is stored with the rule that blocked
it and entered in the shadow book, because a rule whose cost is invisible is a rule nobody can
ever evaluate. The most valuable of the three shadow books is exactly the one holding what the
rules refused.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, replace
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import (
    AgentRun,
    Claim,
    Decision,
    Instrument,
    InvalidationTrigger,
    Portfolio,
    Proposal,
    ShadowEntry,
)
from app.services.errors import Invalid, NotFound
from app.services.investments import (
    books,
    entry,
    frameworks,
    fundamentals,
    gates,
    pricing,
    scoring,
    watching,
)
from app.services.investments import portfolio as pf

ZERO = Decimal(0)

#: The books that hold what did not happen. Created on demand beside the real one.
SHADOW_KINDS = {
    "VETOED": ("SHADOW_VETO", "What I turned down"),
    "BUDGET_EXHAUSTED": ("SHADOW_BUDGET", "What the budget could not fund"),
    "GATE_BLOCKED": ("SHADOW_GATE", "What the rules blocked"),
}

#: The paper book the system's own approved decisions build up.
MIRROR_NAME = "What the system suggested"

#: How long a suggestion stands before it lapses. ⚠ A proposal is made at a price; a month
#: later that price is history and acting on it is acting on a stale judgement.
PROPOSAL_VALID_DAYS = 14

#: The default holding period a suggestion is judged over — months to quarters.
DEFAULT_HORIZON_DAYS = 270

#: Share of the monthly budget a single new position takes, before scaling.
BASE_POSITION_SHARE = Decimal("0.25")
MAX_POSITION_SHARE = Decimal("0.50")


# --- the books ------------------------------------------------------------------------------


def book(db: Session, user_id: uuid.UUID, kind: str, name: str) -> Portfolio:
    """Get or create one of the books. They are never nested — see `Portfolio`."""
    found = db.execute(
        sa.select(Portfolio).where(
            Portfolio.user_id == user_id,
            Portfolio.kind == kind,
            Portfolio.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if found is not None:
        return found
    found = Portfolio(id=uuid.uuid4(), user_id=user_id, name=name, kind=kind)
    db.add(found)
    db.flush()
    return found


def mirror(db: Session, user_id: uuid.UUID) -> Portfolio:
    return book(db, user_id, "MIRROR", MIRROR_NAME)


def shadow(db: Session, user_id: uuid.UUID, reason: str) -> Portfolio:
    kind, name = SHADOW_KINDS[reason]
    return book(db, user_id, kind, name)


# --- what a proposal is made of --------------------------------------------------------------


@dataclass
class Draft:
    """A suggestion, fully assembled, before the rules have looked at it."""

    instrument: Instrument
    action: str
    thesis: str
    confidence: Decimal
    horizon_days: int
    target_amount_inr: Decimal | None
    target_qty: Decimal | None
    triggers: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    ab_score: Decimal | None = None
    quality_earned: Decimal | None = None
    quality_available: Decimal | None = None
    flags_yes: int = 0
    quadrant: str = "UNKNOWN"
    price_snapshot: dict = field(default_factory=dict)
    input_refs: dict = field(default_factory=dict)


def _rupees(amount: Decimal) -> str:
    sign = "-" if amount < 0 else ""
    whole, _, paise = f"{abs(amount):.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}Rs {','.join([*groups, tail])}.{paise}"


def _confidence(ab, quality, flags_yes: int) -> Decimal:
    """How sure the system is, derived from how much it actually knows.

    ⚠ Deliberately mechanical rather than expressive. Confidence is the number calibration is
    measured against — "when it says 80%, is it right 80% of the time" — and a figure a model
    chose because the argument felt strong measures the model's mood. A figure derived from
    coverage measures what was known.
    """
    if quality.available <= 0:
        return ZERO
    coverage = quality.available / Decimal(10)
    strength = quality.ratio or ZERO
    structural = (ab.total or ZERO) / Decimal(10) if ab.is_scored else Decimal("0.5")
    penalty = Decimal("0.08") * flags_yes
    raw = (
        (coverage * Decimal("0.35"))
        + (strength * Decimal("0.40"))
        + (structural * Decimal("0.25"))
        - penalty
    )
    return max(ZERO, min(Decimal(1), raw)).quantize(Decimal("0.001"))


def _thesis(inst: Instrument, ab, quality, flags, mapping) -> str:
    """The argument, assembled from what was measured. Every clause traces to a figure."""
    lines: list[str] = []
    if ab.is_scored and mapping is not None:
        bits = [c.detail for c in ab.components if c.points and c.points > 0]
        lines.append(
            f"{inst.name} clears {mapping.b_bottleneck}, which "
            + (bits[0] if bits else "is in the framework")
            + f". Structural score {ab.total} of 10."
        )
    else:
        lines.append(
            f"{inst.name} is outside the framework, so this rests on the business and the "
            "price alone."
        )

    strong = [p for p in quality.parts if p.points is not None and p.points == p.available]
    weak = [p for p in quality.parts if p.points is not None and p.points == ZERO]
    if strong:
        lines.append("What is good: " + "; ".join(f"{p.name} — {p.detail}" for p in strong) + ".")
    if weak:
        lines.append("What is not: " + "; ".join(f"{p.name} — {p.detail}" for p in weak) + ".")
    if quality.unknown:
        lines.append(
            "Not measured: "
            + ", ".join(quality.unknown)
            + " — so this rests on "
            + f"{quality.earned} of {quality.available} available points, "
            + f"not on {quality.possible}."
        )
    # ⚠ Said separately from the gaps, because they are a different fact. "Return on capital
    # was not measured" invites someone to go and measure it; "return on capital does not
    # describe a bank" does not.
    if getattr(quality, "not_applicable", None):
        lines.append(
            "Does not apply to this kind of company: " + ", ".join(quality.not_applicable) + "."
        )
    if (history := getattr(quality, "history", None)) and (why := history.why()):
        lines.append(f"Depth of reading: {why}.")
    raised = [f for f in flags if f.verdict == "YES"]
    if raised:
        lines.append(
            "Flags standing: " + "; ".join(f"#{f.number} {f.evidence}" for f in raised) + "."
        )
    return "\n".join(lines)


def _triggers_for(db: Session, inst: Instrument, quality, price: Decimal | None) -> list[dict]:
    """What would prove this wrong — each a metric, a comparison, a threshold and a date.

    ⚠ Built from figures that actually exist for this company, so each one can be checked
    later by the same code that computed it. A condition nothing can evaluate is decoration.
    """
    horizon = dt.date.today() + dt.timedelta(days=DEFAULT_HORIZON_DAYS)
    out: list[dict] = []

    roce = next((p for p in quality.parts if p.name == "roce"), None)
    if roce is not None and roce.points is not None:
        out.append(
            {
                "metric_key": "roce",
                "comparator": "LT",
                "threshold": Decimal(12),
                "unit": "pct",
                "window_until": horizon,
                "description": (
                    "Return on capital falls below 12% in the next annual filing. That is the "
                    "level at which the quality argument stops holding."
                ),
            }
        )
    cash = next((p for p in quality.parts if p.name == "cash_conversion"), None)
    if cash is not None and cash.points is not None:
        out.append(
            {
                "metric_key": "cash_conversion",
                "comparator": "LT",
                "threshold": Decimal("0.6"),
                "unit": "ratio",
                "window_until": horizon,
                "description": (
                    "Less than 60 paise of each rupee of profit arrives as cash in the next "
                    "annual filing — profit that never becomes cash is not profit yet."
                ),
            }
        )
    if price is not None:
        floor = (price * Decimal("0.75")).quantize(Decimal("0.01"))
        out.append(
            {
                "metric_key": "price",
                "comparator": "LT",
                "threshold": floor,
                "unit": "inr",
                "window_until": horizon,
                "description": (
                    f"The price falls below {_rupees(floor)}, a quarter below where this was "
                    "suggested, without the accounts explaining it."
                ),
            }
        )
    return out


def _claims_for(quality, flags) -> list[dict]:
    """The falsifiable assertions. These are what make measurement possible in months."""
    due = dt.date.today() + dt.timedelta(days=DEFAULT_HORIZON_DAYS)
    out: list[dict] = []
    for part in quality.parts:
        if part.points is None or part.points == ZERO:
            continue
        if part.name == "roce":
            out.append(
                {
                    "claim_text": "Return on capital stays at or above 15%.",
                    "metric_key": "roce",
                    "comparator": "GTE",
                    "threshold": Decimal(15),
                    "due_by": due,
                }
            )
        elif part.name == "cash_conversion":
            out.append(
                {
                    "claim_text": "Profit keeps arriving as cash, at or above 0.8.",
                    "metric_key": "cash_conversion",
                    "comparator": "GTE",
                    "threshold": Decimal("0.8"),
                    "due_by": due,
                }
            )
        elif part.name == "margin_of_safety":
            out.append(
                {
                    "claim_text": (
                        "Earnings grow, so the margin of safety is not merely a low price."
                    ),
                    "metric_key": "pat",
                    "comparator": "GT",
                    "threshold": ZERO,
                    "due_by": due,
                }
            )
    for flag in flags:
        if flag.verdict == "YES" and flag.number == 8:
            out.append(
                {
                    "claim_text": "Margins stop deteriorating as revenue grows.",
                    "metric_key": "pbt_margin",
                    "comparator": "GTE",
                    "threshold": ZERO,
                    "due_by": due,
                }
            )
    return out


def _size(book_row: Portfolio, confidence: Decimal, price: Decimal | None) -> tuple:
    """How much, and whether one share is even affordable.

    ⚠ India has no fractional equity. A company at Rs 17,000 a share simply cannot be sized at
    Rs 8,000, and the honest answer is to say so and earmark rather than to round.
    """
    budget = book_row.monthly_budget_inr or Decimal(30000)
    target = (budget * BASE_POSITION_SHARE * (Decimal("0.5") + confidence)).quantize(
        Decimal("0.01")
    )
    ceiling = budget * MAX_POSITION_SHARE
    target = min(target, ceiling)
    if price is None or price <= 0:
        return target, None, "ADD"
    if price > ceiling:
        return ceiling, None, "ACCUMULATE_POOL"
    qty = (target / price).quantize(Decimal(1))
    if qty <= 0:
        return price.quantize(Decimal("0.01")), Decimal(1), "ADD"
    return (qty * price).quantize(Decimal("0.01")), qty, "ADD"


def draft_for(
    db: Session, book_row: Portfolio, inst: Instrument, spec: dict, held: set[uuid.UUID]
) -> Draft | None:
    """Assemble a suggestion for one company, or None when there is nothing to suggest."""
    mapping = frameworks.live_mapping(db, inst.id)
    ab = frameworks.ab_score(mapping, spec)

    periods = fundamentals.by_period(db, inst.id, limit=6)
    years = [p for p in periods if "Q" not in p]
    shares = scoring._shares(periods, years[0]) if years else None
    mark = pricing.latest(db, [inst.id]).get(inst.id)
    price = mark.price if mark else None
    market_cap = (price * shares) if (price is not None and shares) else None

    quality = scoring.quality_score(db, inst, spec, market_cap=market_cap)
    flags = scoring.computed_flags(db, inst, price=price)
    flags_yes = sum(1 for f in flags if f.verdict == "YES")
    quadrant = scoring.quadrant(quality, flags_yes >= 2)

    confidence = _confidence(ab, quality, flags_yes)
    amount, qty, action = _size(book_row, confidence, price)
    if inst.id not in held and action == "ADD":
        action = "INITIATE"

    return Draft(
        instrument=inst,
        action=action,
        thesis=_thesis(inst, ab, quality, flags, mapping),
        confidence=confidence,
        horizon_days=DEFAULT_HORIZON_DAYS,
        target_amount_inr=amount,
        target_qty=qty,
        triggers=_triggers_for(db, inst, quality, price),
        claims=_claims_for(quality, flags),
        ab_score=ab.total,
        quality_earned=quality.earned,
        quality_available=quality.available,
        flags_yes=flags_yes,
        quadrant=quadrant,
        price_snapshot=(
            {
                "price": str(price),
                "observed_at": mark.observed_at.isoformat(),
                "source": mark.source,
                "age": mark.age_text,
            }
            if mark
            else {"price": None, "reason": "no price observed"}
        ),
        input_refs={
            "framework_version": str(mapping.framework_version_id) if mapping else None,
            "fundamentals": sorted(
                {
                    str(periods[p]["_source_item_id"])
                    for p in years
                    if "_source_item_id" in periods[p]
                }
            ),
            "years_read": len(years),
        },
    )


# --- writing it down --------------------------------------------------------------------


#: Asset classes the framework is about. ⚠ Crypto and mutual funds are deliberately outside
#: it — tracked and reported, never proposed — so they belong in neither half of this ratio.
FRAMEWORK_CLASSES = frozenset({"EQUITY_IN", "EQUITY_US"})


def _off_framework_share(db: Session, portfolio_id: uuid.UUID, spec: dict) -> Decimal:
    """How much of the EQUITY book sits in names the framework does not cover.

    ⚠ Equities only, and the first version of this was wrong in a way worth recording.
    Counting every holding put crypto and the mutual funds in the denominator AND the
    numerator — they have no framework mapping, because the framework was never about them —
    and the off-framework share came out at 39.8%, eight times its ceiling. Every equity
    outside the framework was then blocked by a rule measuring something else entirely.
    """
    positions = [p for p in pf.positions(db, portfolio_id) if p.asset_class in FRAMEWORK_CLASSES]
    if not positions:
        return ZERO
    total = sum((p.cost_basis_inr for p in positions), ZERO)
    if not total:
        return ZERO
    outside = ZERO
    for pos in positions:
        mapping = frameworks.live_mapping(db, pos.instrument_id)
        if mapping is None or mapping.off_framework:
            outside += pos.cost_basis_inr
    return outside / total


def _month_count(db: Session, portfolio_id: uuid.UUID, today: dt.date) -> int:
    """Suggestions already made this calendar month, blocked ones excluded."""
    since = dt.datetime(today.year, today.month, 1, tzinfo=dt.UTC)
    return (
        db.execute(
            sa.select(sa.func.count())
            .select_from(Proposal)
            .where(
                Proposal.portfolio_id == portfolio_id,
                Proposal.created_at >= since,
                Proposal.status == "PENDING",
                Proposal.action.in_(tuple(gates.BUYING)),
            )
        ).scalar_one()
        or 0
    )


def write(
    db: Session,
    *,
    book_row: Portfolio,
    user_id: uuid.UUID,
    draft: Draft,
    verdict: gates.Verdict,
    batch_id: uuid.UUID,
    framework_version_id: uuid.UUID,
    agent_run_id: uuid.UUID | None = None,
) -> Proposal:
    """Store the suggestion — or the refusal, which is stored just as carefully.

    ⚠ A blocked proposal is written with the rule that blocked it and entered in the shadow
    book. Discarding refusals would make the rails unmeasurable: there would be no way to ever
    ask whether they were protecting or merely obstructing, and a rule nobody can evaluate is
    a rule that survives on faith.
    """
    blocked = verdict.blocked_by
    row = Proposal(
        id=uuid.uuid4(),
        batch_id=batch_id,
        agent_run_id=agent_run_id,
        portfolio_id=book_row.id,
        instrument_id=draft.instrument.id,
        action=draft.action,
        target_amount_inr=draft.target_amount_inr,
        target_qty=draft.target_qty,
        horizon_days=draft.horizon_days,
        thesis=draft.thesis,
        confidence=draft.confidence,
        framework_version_id=framework_version_id,
        ab_score=draft.ab_score,
        quality_earned=draft.quality_earned,
        quality_available=draft.quality_available,
        reflexivity_flags_yes=draft.flags_yes,
        quadrant=draft.quadrant,
        price_snapshot=draft.price_snapshot,
        input_refs=draft.input_refs,
        gate_results=verdict.as_dict(),
        status="BLOCKED" if blocked else "PENDING",
        blocked_by=blocked,
    )
    db.add(row)
    db.flush()

    # ⚠ **Claims are written whether or not the gates let the idea through**, and this is the
    # single most consequential line in the module. They used to be written only for
    # proposals that survived every gate — and in a market where nothing is cheap, nothing
    # survives. Fifty-seven suggestions were raised and fifty-seven were blocked, so the
    # system produced exactly zero falsifiable predictions in its first month of running.
    #
    # That is the same defect as a scoring rule nobody can satisfy, one layer up: the
    # go/no-go verdict asks for 150 resolved claims within a year, and at zero a night it
    # would still be at zero in a year — an unanswerable question rather than a hard one, and
    # nobody would find out until the year was over.
    #
    # Calibration is a property of the JUDGE, not of the purchases. A forecast is falsifiable
    # whether or not anyone acted on it, and a weather forecaster is not graded only on the
    # days someone carried an umbrella. The module already half-agreed: a blocked idea is
    # entered in the shadow book and tracked at the price it would have happened at, so the
    # money was followed while the reasoning was thrown away. That is half a measurement.
    _record_claims(db, row, draft)

    if blocked:
        _shadow(db, user_id, row, draft, "GATE_BLOCKED")
        return row

    # ⚠ Triggers, unlike claims, stay with ideas that were actually offered. A trigger asks
    # "what would make me sell this" — a question about a position, and there is no position.
    # Arming them on blocked ideas would raise exit alerts about holdings that do not exist
    # and quietly wreck the trigger-discipline measure, which counts whether fired triggers
    # were acted on.
    for trigger in draft.triggers:
        db.add(
            InvalidationTrigger(
                id=uuid.uuid4(),
                proposal_id=row.id,
                instrument_id=draft.instrument.id,
                **trigger,
            )
        )
    db.flush()
    return row


def _record_claims(db: Session, row: Proposal, draft: Draft) -> int:
    """Write this thesis's falsifiable assertions, skipping ones already outstanding.

    ⚠ **Deduplicated, and without that this change would be worse than the bug it fixes.**
    The same company is reconsidered every single night and its claims are computed from filed
    figures, so they come out identical each time. Written naively that is roughly forty
    near-identical rows a night — fifteen thousand a year — and "150 resolved claims" would be
    reached inside a week by a hundred and fifty copies of the same three predictions. The
    measure would read as a large sample and be a sample of one.

    So a claim is recorded only where no OPEN claim already asserts the same thing about the
    same company: same metric, same comparator, same threshold. A genuinely new assertion —
    a changed threshold, or the same one again after the last resolved — is written.

    ⚠ Written with the proposal and never afterwards, for the same reason as always: an
    assertion added once the outcome is visible is an assertion chosen to be satisfied.
    """
    if not draft.claims:
        return 0

    outstanding = {
        (metric, comparator, threshold)
        for metric, comparator, threshold in db.execute(
            sa.select(Claim.metric_key, Claim.comparator, Claim.threshold)
            .join(Proposal, Claim.proposal_id == Proposal.id)
            .where(
                Claim.status == "OPEN",
                Proposal.instrument_id == draft.instrument.id,
            )
        ).all()
    }

    written = 0
    for claim in draft.claims:
        key = (claim.get("metric_key"), claim.get("comparator"), claim.get("threshold"))
        if key in outstanding:
            continue
        outstanding.add(key)
        db.add(Claim(id=uuid.uuid4(), proposal_id=row.id, **claim))
        written += 1
    if written:
        db.flush()
    return written


def _shadow(
    db: Session, user_id: uuid.UUID, proposal: Proposal, draft: Draft, reason: str
) -> ShadowEntry | None:
    """Track what did not happen, at the price it would have happened at."""
    raw = (draft.price_snapshot or {}).get("price")
    if not raw:
        return None
    price = Decimal(str(raw))
    if price <= 0:
        return None
    quantity = draft.target_qty or (
        ((draft.target_amount_inr or ZERO) / price).quantize(Decimal("0.00000001"))
    )
    if quantity <= 0:
        return None

    existing = db.execute(
        sa.select(ShadowEntry).where(ShadowEntry.proposal_id == proposal.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    entry = ShadowEntry(
        id=uuid.uuid4(),
        portfolio_id=shadow(db, user_id, reason).id,
        proposal_id=proposal.id,
        reason=reason,
        entry_price=price,
        entry_date=dt.date.today(),
        quantity=quantity,
    )
    db.add(entry)
    db.flush()
    return entry


# --- what the human does about it ------------------------------------------------------------


def effective_status(db: Session, proposal: Proposal, *, today: dt.date | None = None) -> str:
    """What state a proposal is really in.

    ⚠ Derived, never stored. The row carries only what the SYSTEM decided as it wrote it; what
    the person decided lives in `decisions`. An editable status column on an append-only table
    would drift out of step with the decision record, and nothing could say which was right.
    """
    if proposal.status == "BLOCKED":
        return "BLOCKED"
    decision = db.execute(
        sa.select(Decision).where(Decision.proposal_id == proposal.id)
    ).scalar_one_or_none()
    if decision is not None:
        return {"APPROVE": "APPROVED", "REJECT": "REJECTED", "MODIFY": "MODIFIED"}[decision.outcome]
    today = today or dt.date.today()
    if (today - proposal.created_at.date()).days > PROPOSAL_VALID_DAYS:
        return "EXPIRED"
    return "PENDING"


def decide(
    db: Session,
    proposal: Proposal,
    *,
    user_id: uuid.UUID,
    outcome: str,
    reason: str,
    modified_amount_inr: Decimal | None = None,
    via: str = "WEB",
    today: dt.date | None = None,
) -> Decision:
    """Approve, reject or modify — with a reason, which is not optional.

    ⚠ The reason is required by the database, not merely asked for. It is the data that
    eventually reveals what kinds of suggestion keep being turned down, and that is the only
    way the system ever learns anything about its own judgement. A decision without one
    records that something happened and nothing about why.

    Approving updates the MIRROR book only. The real book is the user's word and is never
    written by a machine — if they act differently in life, they say so, and the gap between
    the two books is one of the most interesting numbers this produces.
    """
    if outcome not in ("APPROVE", "REJECT", "MODIFY"):
        raise Invalid("a decision is approve, reject or modify")
    if not (reason or "").strip():
        raise Invalid("a decision needs a reason in your own words")

    state = effective_status(db, proposal, today=today)
    if state == "BLOCKED":
        raise Invalid("that suggestion was blocked by a rule and was never offered")
    if state in ("APPROVED", "REJECTED", "MODIFIED"):
        raise Invalid(f"that suggestion has already been {state.lower()}")
    if state == "EXPIRED":
        raise Invalid("that suggestion has lapsed — it was made at a price that is now history")

    row = Decision(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        decided_at=dt.datetime.now(dt.UTC),
        outcome=outcome,
        modified_amount_inr=modified_amount_inr,
        reason_text=reason.strip(),
        decided_via=via,
    )
    db.add(row)

    if outcome == "APPROVE" or outcome == "MODIFY":
        _fill_paper_books(db, user_id, proposal, modified_amount_inr)

    if outcome == "REJECT":
        # ⚠ Read in aggregate on a schedule, never after a name that got away. A rejected idea
        # that rose is far more memorable than one that fell, and browsing this book casually
        # trains worse judgement rather than better.
        _shadow_from_proposal(db, user_id, proposal, "VETOED")
    else:
        for trigger in db.execute(
            sa.select(InvalidationTrigger).where(InvalidationTrigger.proposal_id == proposal.id)
        ).scalars():
            trigger.status = "ARMED"
    db.flush()
    return row


def _fill_paper_books(
    db: Session,
    user_id: uuid.UUID,
    proposal: Proposal,
    modified_amount_inr: Decimal | None,
) -> None:
    """Write the approved fill into both paper books.

    ⚠ Both, and they are not duplicates. `MIRROR` started as a copy of what was really held,
    so it answers "what would my portfolio look like if I had followed Acero from here".
    `AI_CLEAN` started from nothing, so it answers "what has Acero itself produced". One
    cannot be derived from the other, and merging them would lose whichever question was not
    asked.

    ⚠ The REAL book is never touched. What the user does in life is their word, entered the
    same way every other transaction is — and the gap between the two is one of the most
    interesting numbers this module produces.
    """
    raw = (proposal.price_snapshot or {}).get("price")
    if not raw:
        return
    price = Decimal(str(raw))
    if price <= 0:
        return

    amount = modified_amount_inr or proposal.target_amount_inr or ZERO
    quantity = proposal.target_qty or (amount / price if amount else ZERO)
    if quantity <= 0:
        return

    instrument = db.get(Instrument, proposal.instrument_id)
    if instrument is None:
        return

    note = f"approved suggestion {proposal.id}"
    for kind in ("MIRROR", "AI_CLEAN"):
        book_row = books.ensure(db, user_id, kind)
        entry.record_paper(
            db,
            book_row.id,
            instrument=instrument,
            trade_date=dt.date.today(),
            quantity=quantity,
            price=price,
            note=note,
        )


def _shadow_from_proposal(
    db: Session, user_id: uuid.UUID, proposal: Proposal, reason: str
) -> ShadowEntry | None:
    raw = (proposal.price_snapshot or {}).get("price")
    if not raw:
        return None
    price = Decimal(str(raw))
    if price <= 0:
        return None
    quantity = proposal.target_qty or (
        ((proposal.target_amount_inr or ZERO) / price).quantize(Decimal("0.00000001"))
    )
    if quantity <= 0:
        return None
    existing = db.execute(
        sa.select(ShadowEntry).where(
            ShadowEntry.proposal_id == proposal.id,
            ShadowEntry.reason == reason,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    entry = ShadowEntry(
        id=uuid.uuid4(),
        portfolio_id=shadow(db, user_id, reason).id,
        proposal_id=proposal.id,
        reason=reason,
        entry_price=price,
        entry_date=dt.date.today(),
        quantity=quantity,
    )
    db.add(entry)
    db.flush()
    return entry


# --- the run ------------------------------------------------------------------------------------


@dataclass
class Batch:
    """What one evening produced."""

    run_id: uuid.UUID
    batch_id: uuid.UUID
    proposed: list[Proposal] = field(default_factory=list)
    blocked: list[Proposal] = field(default_factory=list)
    considered: int = 0

    def detail(self) -> dict:
        return {
            "considered": self.considered,
            "proposed": len(self.proposed),
            "blocked": len(self.blocked),
            "blockers": sorted({p.blocked_by for p in self.blocked if p.blocked_by}),
        }


# --- when a condition you wrote comes true ---------------------------------------------------
#
# ⚠ **A system that writes invalidation conditions and then rationalises past them has quietly
# stopped being a system.** Until now a fired condition raised a notification and nothing else,
# which left the acting entirely to whoever happened to read it — and "did the system act when
# its own condition fired" is the one go/no-go criterion that is not statistical. If it ignored
# its own conditions even a few times, it does not get real money whatever the returns say.
#
# ⚠ **The proposal it raises is never a buy.** A condition firing is the thesis being
# contradicted, and the only honest responses are to reduce, to leave, or to say out loud why
# neither — which is what a HOLD carrying a reason is. A design that let a fired condition
# produce "add more" would have invented averaging down as a policy.


#: Below this fraction of the position still held, trimming is not worth the charges and the
#: honest suggestion is to leave entirely.
MIN_TRIM_FRACTION = Decimal("0.25")


def response_to(fired: list, held: set[uuid.UUID]) -> str:
    """What a fired condition asks for. ⚠ Never a purchase; see above."""
    return "EXIT" if len(fired) > 1 else "TRIM"


def on_triggers_fired(
    db: Session,
    user_id: uuid.UUID,
    watch,
    *,
    occurrence_key: str,
    today: dt.date | None = None,
) -> Batch:
    """Raise a suggestion for every holding whose own invalidation condition came true.

    ⚠ Formed and written the way the evening batch is, through the same gates and into the
    same books — because a proposal raised in a hurry is exactly the kind that should be held
    to the rules hardest. The only difference is which companies are looked at and that the
    action is a reduction.

    ⚠ Zero is a normal outcome and the run is still recorded. A system that leaves a trace
    only on the days it acted cannot be measured against the days it should have.
    """
    today = today or dt.date.today()
    started = dt.datetime.now(dt.UTC)
    batch_id = uuid.uuid4()

    version = frameworks.current(db)
    spec = version.spec
    real = db.execute(
        sa.select(Portfolio).where(
            Portfolio.user_id == user_id,
            Portfolio.kind == "REAL",
            Portfolio.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if real is None:
        raise NotFound("no REAL portfolio")
    mirror_book = mirror(db, user_id)
    held = {p.instrument_id for p in pf.positions(db, real.id)}

    by_instrument: dict[uuid.UUID, list] = defaultdict(list)
    for fired in getattr(watch, "fired", ()):
        by_instrument[fired.trigger.instrument_id].append(fired)

    decided: list[tuple[Draft, gates.Verdict]] = []
    for instrument_id, entries in by_instrument.items():
        inst = db.get(Instrument, instrument_id)
        if inst is None:
            continue
        draft = draft_for(db, mirror_book, inst, spec, held)
        if draft is None:
            continue

        action = response_to(entries, held)
        why = "; ".join(
            f"{row.trigger.description} — {row.trigger.metric_key} is {row.value}"
            for row in entries
        )
        draft = replace(
            draft,
            action=action,
            thesis=(
                f"A condition written when this position was taken has come true: {why}. "
                f"{draft.thesis}"
            ),
        )

        mapping = frameworks.live_mapping(db, inst.id)
        candidate = gates.Candidate(
            instrument=inst,
            action=draft.action,
            mapping=mapping,
            ab_score=draft.ab_score,
            quality=scoring.quality_score(db, inst, spec, market_cap=_cap(db, inst, draft)),
            quadrant=draft.quadrant,
            confidence=draft.confidence,
            horizon_days=draft.horizon_days,
            triggers=draft.triggers,
            target_amount_inr=draft.target_amount_inr,
            off_framework=bool(mapping and mapping.off_framework),
            off_framework_share=ZERO,
            in_batch=0,
            this_month=0,
        )
        decided.append((draft, gates.evaluate(db, mirror_book.id, candidate)))

    passing = sum(1 for _, v in decided if v.passed)
    run = AgentRun(
        id=uuid.uuid4(),
        agent_name="trigger_response",
        occurrence_key=occurrence_key,
        started_at=started,
        finished_at=dt.datetime.now(dt.UTC),
        status="OK",
        inputs_seen=sum(len(v) for v in by_instrument.values()),
        inputs_material=len(by_instrument),
        proposals_emitted=passing,
        notes=f"{len(decided) - passing} blocked by the rules",
    )
    db.add(run)
    db.flush()

    proposed: list[Proposal] = []
    blocked: list[Proposal] = []
    for draft, verdict in decided:
        row = write(
            db,
            book_row=mirror_book,
            user_id=user_id,
            draft=draft,
            verdict=verdict,
            batch_id=batch_id,
            framework_version_id=version.id,
            agent_run_id=run.id,
        )
        (proposed if verdict.passed else blocked).append(row)
    db.flush()
    return Batch(
        run_id=run.id,
        batch_id=batch_id,
        proposed=proposed,
        blocked=blocked,
        considered=len(decided),
    )


def synthesise(
    db: Session,
    user_id: uuid.UUID,
    *,
    occurrence_key: str,
    today: dt.date | None = None,
) -> Batch:
    """Look at every tracked company and decide whether anything is worth suggesting.

    ⚠ Zero suggestions is a normal and frequently correct outcome, and the run is recorded
    either way. A system that only leaves a trace on the days it acted can never be measured
    against the days it should have acted and did not.
    """
    today = today or dt.date.today()
    started = dt.datetime.now(dt.UTC)
    batch_id = uuid.uuid4()

    version = frameworks.current(db)
    spec = version.spec
    real = db.execute(
        sa.select(Portfolio).where(
            Portfolio.user_id == user_id,
            Portfolio.kind == "REAL",
            Portfolio.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if real is None:
        raise NotFound("no REAL portfolio")
    mirror_book = mirror(db, user_id)

    held = {p.instrument_id for p in pf.positions(db, real.id)}
    share = _off_framework_share(db, real.id, spec)
    month = _month_count(db, mirror_book.id, today)

    tracked = list(
        db.execute(
            sa.select(Instrument)
            .where(
                Instrument.deleted_at.is_(None),
                Instrument.is_tracked.is_(True),
                Instrument.asset_class == "EQUITY_IN",
            )
            .order_by(Instrument.symbol)
        ).scalars()
    )

    # ⚠ Every judgement is formed BEFORE anything is written.
    #
    # The run row is append-only and so cannot be opened at the start and closed at the end —
    # the database refused exactly that, which is the guard working. Doing the thinking first
    # also means a run that fails halfway writes nothing at all, instead of leaving half a
    # batch and a record claiming the evening completed.
    decided: list[tuple[Draft, gates.Verdict]] = []
    passing = 0
    for inst in tracked:
        draft = draft_for(db, mirror_book, inst, spec, held)
        if draft is None:
            continue
        mapping = frameworks.live_mapping(db, inst.id)
        candidate = gates.Candidate(
            instrument=inst,
            action=draft.action,
            mapping=mapping,
            ab_score=draft.ab_score,
            quality=scoring.quality_score(db, inst, spec, market_cap=_cap(db, inst, draft)),
            quadrant=draft.quadrant,
            confidence=draft.confidence,
            horizon_days=draft.horizon_days,
            triggers=draft.triggers,
            target_amount_inr=draft.target_amount_inr,
            off_framework=bool(mapping and mapping.off_framework),
            off_framework_share=share,
            in_batch=passing,
            this_month=month + passing,
        )
        verdict = gates.evaluate(db, mirror_book.id, candidate)
        if verdict.passed:
            passing += 1
        decided.append((draft, verdict))

        # ⚠ Remember the judgement, not just the suggestion. A score is made at a moment with
        # the data available then; recomputing it later with today's figures would show a
        # company that improved from 4 to 8 as having always been 8, and the improvement —
        # the most interesting thing about it — would be invisible. Written only on a change.
        watching.record_score(
            db,
            inst,
            framework_version_id=version.id,
            ab=frameworks.ab_score(mapping, spec),
            quality=candidate.quality,
            flags=scoring.computed_flags(
                db,
                inst,
                price=(
                    Decimal(str(draft.price_snapshot["price"]))
                    if draft.price_snapshot.get("price")
                    else None
                ),
            ),
            quadrant=draft.quadrant,
            price=(
                Decimal(str(draft.price_snapshot["price"]))
                if draft.price_snapshot.get("price")
                else None
            ),
            years_read=draft.input_refs.get("years_read", 0),
            today=today,
        )

    run = AgentRun(
        id=uuid.uuid4(),
        agent_name="evening_synthesis",
        occurrence_key=occurrence_key,
        started_at=started,
        finished_at=dt.datetime.now(dt.UTC),
        status="OK",
        inputs_seen=len(decided),
        inputs_material=passing,
        proposals_emitted=passing,
        notes=f"{len(decided) - passing} blocked by the rules",
    )
    db.add(run)
    db.flush()

    batch = Batch(run_id=run.id, batch_id=batch_id, considered=len(decided))
    for draft, verdict in decided:
        row = write(
            db,
            book_row=mirror_book,
            user_id=user_id,
            draft=draft,
            verdict=verdict,
            batch_id=batch_id,
            framework_version_id=version.id,
            agent_run_id=run.id,
        )
        (batch.blocked if row.status == "BLOCKED" else batch.proposed).append(row)
    db.flush()
    return batch


def _cap(db: Session, inst: Instrument, draft: Draft) -> Decimal | None:
    periods = fundamentals.by_period(db, inst.id, limit=6)
    years = [p for p in periods if "Q" not in p]
    shares = scoring._shares(periods, years[0]) if years else None
    raw = (draft.price_snapshot or {}).get("price")
    if not shares or not raw:
        return None
    return Decimal(str(raw)) * shares


def open_proposals(db: Session, portfolio_id: uuid.UUID) -> list[Proposal]:
    """Suggestions still awaiting a person, newest first."""
    rows = db.execute(
        sa.select(Proposal)
        .where(Proposal.portfolio_id == portfolio_id, Proposal.status == "PENDING")
        .order_by(Proposal.created_at.desc())
    ).scalars()
    return [p for p in rows if effective_status(db, p) == "PENDING"]


def recent(db: Session, portfolio_id: uuid.UUID, *, limit: int = 40) -> list[Proposal]:
    """Everything recent, decided or not — including what the rules refused."""
    return list(
        db.execute(
            sa.select(Proposal)
            .where(Proposal.portfolio_id == portfolio_id)
            .order_by(Proposal.created_at.desc())
            .limit(limit)
        ).scalars()
    )
