"""Checking whether what was claimed came true, and whether what would disprove it happened.

A thesis that is never checked is a story. This module is the half of the decision loop that
makes the other half worth having: it walks the invalidation conditions against each day's
facts, resolves claims when their deadline arrives, and computes the handful of measures that
can say something honest about the system long before its returns can.

⚠ **The measurement problem this exists to solve.** At thirty-odd decisions a year, nothing
statistical can be said about returns for years — the conventional floor is about thirty
observations and that is a floor rather than a standard. But each thesis makes several
specific, checkable assertions and carries at least two invalidation conditions, so a year
produces a few hundred testable predictions instead of thirty outcomes. That is the difference
between knowing in months and knowing in decades, and it is the entire reason claims are
written down.

⚠ **A number computed on too little evidence is worse than no number**, because it will be
believed. Every measure here reports its sample size and refuses to produce a figure below a
stated minimum.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import (
    Claim,
    Decision,
    Instrument,
    InvalidationTrigger,
    PriceObservation,
    Proposal,
)
from app.services.investments import fundamentals, scoring

ZERO = Decimal(0)

#: Below this many resolved observations a measure reports "not enough yet" and no figure.
#: ⚠ Not caution for its own sake: a precision computed over six outcomes is noise that reads
#: exactly like a finding, and the reader has no way to tell which they are looking at.
MIN_OBSERVATIONS = 20

#: How long after a condition fires the system is expected to have responded. Trigger
#: discipline is the one measure that is not statistical — a system that writes invalidation
#: conditions and then reasons past them has quietly stopped being a system.
RESPONSE_DAYS = 7


def current_value(db: Session, instrument_id: uuid.UUID, metric: str) -> Decimal | None:
    """What a watched metric stands at now. None where it cannot be computed.

    ⚠ None is a real answer and must not become zero. A condition that cannot be evaluated has
    not been satisfied — it is unevaluated, and firing on an absent figure would be the system
    reacting to its own blindness.
    """
    if metric == "price":
        row = db.execute(
            sa.select(PriceObservation.price)
            .where(
                PriceObservation.instrument_id == instrument_id,
                PriceObservation.quality == "OK",
            )
            .order_by(PriceObservation.observed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return row

    periods = fundamentals.by_period(db, instrument_id, limit=6)
    years = [p for p in periods if "Q" not in p]
    if not years:
        return None
    newest = years[0]

    if metric == "roce":
        return scoring._roce(periods, newest)
    if metric == "roe":
        return scoring._roe(periods, newest)
    if metric == "cash_conversion":
        ocf = scoring._get(periods, newest, "ocf")
        pat = scoring._get(periods, newest, "pat")
        return (ocf / pat) if (ocf is not None and pat) else None
    if metric == "pbt_margin":
        pbt = scoring._get(periods, newest, "pbt")
        revenue = scoring._get(periods, newest, "revenue")
        return (pbt / revenue) if (pbt is not None and revenue) else None
    return scoring._get(periods, newest, metric)


def _compare(value: Decimal, comparator: str, threshold: Decimal) -> bool:
    return {
        "LT": value < threshold,
        "LTE": value <= threshold,
        "GT": value > threshold,
        "GTE": value >= threshold,
        "EQ": value == threshold,
        # A crossing needs a previous value to be a crossing; without one it is treated as the
        # plain comparison, which is the conservative reading.
        "CROSSES_BELOW": value < threshold,
        "CROSSES_ABOVE": value > threshold,
    }.get(comparator, False)


@dataclass
class Fired:
    """One condition that came true, with what made it true."""

    trigger: InvalidationTrigger
    symbol: str
    value: Decimal


@dataclass
class Watch:
    """What one pass of the watcher did."""

    checked: int = 0
    fired: list[Fired] = field(default_factory=list)
    expired: int = 0
    unevaluable: int = 0

    def detail(self) -> dict:
        return {
            "checked": self.checked,
            "fired": len(self.fired),
            "expired": self.expired,
            "could_not_evaluate": self.unevaluable,
        }


def check_triggers(db: Session, *, today: dt.date | None = None) -> Watch:
    """Walk every armed invalidation condition against today's facts.

    ⚠ A condition past its window without firing **expires** rather than lingering. Leaving it
    armed for ever would let it fire years later on an unrelated movement and be read as the
    original thesis failing, which is a worse error than losing the condition.
    """
    today = today or dt.date.today()
    watch = Watch()

    armed = list(
        db.execute(
            sa.select(InvalidationTrigger).where(InvalidationTrigger.status == "ARMED")
        ).scalars()
    )
    if not armed:
        return watch

    names = dict(
        db.execute(
            sa.select(Instrument.id, Instrument.symbol).where(
                Instrument.id.in_({t.instrument_id for t in armed})
            )
        ).all()
    )

    for trigger in armed:
        watch.checked += 1
        value = current_value(db, trigger.instrument_id, trigger.metric_key)
        if value is None:
            # ⚠ Not a pass. An unevaluable condition is unevaluated, and counting it as
            # satisfied would report a clean bill of health nothing ever checked.
            watch.unevaluable += 1
            if trigger.window_until < today:
                trigger.status = "EXPIRED"
                watch.expired += 1
            continue

        if _compare(value, trigger.comparator, trigger.threshold):
            trigger.status = "FIRED"
            trigger.fired_at = dt.datetime.now(dt.UTC)
            trigger.fired_evidence = {
                "metric": trigger.metric_key,
                "value": str(value),
                "comparator": trigger.comparator,
                "threshold": str(trigger.threshold),
                "on": today.isoformat(),
            }
            watch.fired.append(
                Fired(trigger=trigger, symbol=names.get(trigger.instrument_id, "?"), value=value)
            )
        elif trigger.window_until < today:
            trigger.status = "EXPIRED"
            watch.expired += 1

    db.flush()
    return watch


@dataclass
class Resolved:
    """What one pass of claim resolution did."""

    checked: int = 0
    true: int = 0
    false: int = 0
    unverifiable: int = 0

    def detail(self) -> dict:
        return {
            "checked": self.checked,
            "true": self.true,
            "false": self.false,
            "unverifiable": self.unverifiable,
        }


def resolve_claims(db: Session, *, today: dt.date | None = None) -> Resolved:
    """Settle every claim whose deadline has arrived.

    ⚠ A claim that cannot be checked is recorded **unverifiable**, never false. Counting an
    unmeasurable claim against the system would make its accuracy a measure of data coverage
    rather than of judgement — and the two would be impossible to tell apart afterwards.
    """
    today = today or dt.date.today()
    report = Resolved()

    due = list(
        db.execute(sa.select(Claim).where(Claim.status == "OPEN", Claim.due_by <= today)).scalars()
    )
    if not due:
        return report

    instruments = dict(
        db.execute(
            sa.select(Proposal.id, Proposal.instrument_id).where(
                Proposal.id.in_({c.proposal_id for c in due})
            )
        ).all()
    )

    for claim in due:
        report.checked += 1
        instrument_id = instruments.get(claim.proposal_id)
        value = (
            current_value(db, instrument_id, claim.metric_key)
            if instrument_id and claim.metric_key
            else None
        )
        if value is None or claim.comparator is None or claim.threshold is None:
            claim.status = "UNVERIFIABLE"
            claim.resolved_at = dt.datetime.now(dt.UTC)
            claim.resolved_evidence = {"reason": "the figure it asked about could not be read"}
            report.unverifiable += 1
            continue

        held = _compare(value, claim.comparator, claim.threshold)
        claim.status = "TRUE" if held else "FALSE"
        claim.resolved_at = dt.datetime.now(dt.UTC)
        claim.resolved_evidence = {
            "metric": claim.metric_key,
            "value": str(value),
            "comparator": claim.comparator,
            "threshold": str(claim.threshold),
            "on": today.isoformat(),
        }
        report.true += held
        report.false += not held

    db.flush()
    return report


# --- what any of it is worth -------------------------------------------------------------------


@dataclass(frozen=True)
class Measure:
    """One reading, with the sample it rests on.

    ⚠ `value is None` with `n` below the minimum is the honest state for a long time. A figure
    computed over six outcomes reads exactly like a figure computed over six hundred, and the
    reader cannot tell which they are being shown unless the code refuses.
    """

    name: str
    value: Decimal | None
    n: int
    detail: str

    @property
    def is_reportable(self) -> bool:
        return self.value is not None


def claim_accuracy(db: Session) -> Measure:
    """Of the checkable things the theses asserted, what fraction happened?

    The closest thing to a direct measure of whether the reasoning works, and the one that
    reaches a usable sample first.
    """
    rows = db.execute(
        sa.select(Claim.status, sa.func.count())
        .where(Claim.status.in_(("TRUE", "FALSE")))
        .group_by(Claim.status)
    ).all()
    counts = dict(rows)
    true, false = counts.get("TRUE", 0), counts.get("FALSE", 0)
    n = true + false
    if n < MIN_OBSERVATIONS:
        return Measure(
            "claim_accuracy",
            None,
            n,
            f"{n} of {MIN_OBSERVATIONS} resolved claims needed before this means anything",
        )
    return Measure(
        "claim_accuracy",
        (Decimal(true) / Decimal(n)).quantize(Decimal("0.001")),
        n,
        f"{true} of {n} specific assertions came true",
    )


def calibration(db: Session) -> Measure:
    """When it said 80%, was it right 80% of the time?

    Scored with Brier: the mean squared gap between the confidence stated and what actually
    happened, where what happened is the fraction of that thesis's claims that came true.
    **Lower is better**, and 0.25 is what a coin achieves by saying 50% every time.

    ⚠ Overconfidence is the most common and most correctable failure of a system like this,
    and it shows up here before it shows up anywhere else.
    """
    rows = db.execute(
        sa.select(
            Proposal.confidence,
            sa.func.count(Claim.id).filter(Claim.status.in_(("TRUE", "FALSE"))),
            sa.func.count(Claim.id).filter(Claim.status == "TRUE"),
        )
        .join(Claim, Claim.proposal_id == Proposal.id)
        .group_by(Proposal.id, Proposal.confidence)
    ).all()

    scored = [
        (confidence, Decimal(true) / Decimal(resolved))
        for confidence, resolved, true in rows
        if resolved
    ]
    if len(scored) < MIN_OBSERVATIONS:
        return Measure(
            "calibration",
            None,
            len(scored),
            f"{len(scored)} of {MIN_OBSERVATIONS} settled theses needed; a calibration curve "
            "over fewer says more about the sample than about the system",
        )
    brier = sum(((c - outcome) ** 2 for c, outcome in scored), ZERO) / Decimal(len(scored))
    return Measure(
        "calibration",
        brier.quantize(Decimal("0.001")),
        len(scored),
        f"Brier {brier:.3f} over {len(scored)} theses — lower is better, and 0.250 is what "
        "saying 50% to everything achieves",
    )


def trigger_discipline(db: Session, *, today: dt.date | None = None) -> Measure:
    """When a condition fired, did anything happen?

    ⚠ The one measure here that is **not statistical**. A system that writes invalidation
    conditions and then reasons past them has quietly stopped being a system, and a single
    ignored firing is a finding rather than a data point. So this reports from the first
    firing, with its count, rather than waiting for a sample.
    """
    today = today or dt.date.today()
    fired = list(
        db.execute(
            sa.select(InvalidationTrigger).where(
                InvalidationTrigger.status == "FIRED",
                InvalidationTrigger.fired_at.isnot(None),
            )
        ).scalars()
    )
    settled = [t for t in fired if (today - t.fired_at.date()).days >= RESPONSE_DAYS]
    if not settled:
        return Measure(
            "trigger_discipline",
            None,
            0,
            "no invalidation condition has fired and had time to be answered yet",
        )

    answered = 0
    for trigger in settled:
        responded = db.execute(
            sa.select(Proposal.id)
            .where(
                Proposal.instrument_id == trigger.instrument_id,
                Proposal.action.in_(("TRIM", "EXIT")),
                Proposal.created_at >= trigger.fired_at,
                Proposal.created_at <= trigger.fired_at + dt.timedelta(days=RESPONSE_DAYS),
            )
            .limit(1)
        ).scalar_one_or_none()
        answered += responded is not None

    return Measure(
        "trigger_discipline",
        (Decimal(answered) / Decimal(len(settled))).quantize(Decimal("0.001")),
        len(settled),
        f"{answered} of {len(settled)} fired conditions produced a response within "
        f"{RESPONSE_DAYS} days"
        + ("" if answered == len(settled) else " — anything below all of them is a problem"),
    )


def decision_record(db: Session) -> Measure:
    """How often the user agreed with the system. Not a score — a description.

    ⚠ Deliberately not framed as accuracy. Whether the user's vetoes add to or subtract from
    the machine's judgement is answered by the shadow book over years, not by counting
    agreements, and a high agreement rate could equally mean the system is good or that it has
    learned to suggest only what will be accepted.
    """
    rows = db.execute(sa.select(Decision.outcome, sa.func.count()).group_by(Decision.outcome)).all()
    counts = dict(rows)
    n = sum(counts.values())
    if not n:
        return Measure("decision_record", None, 0, "no suggestion has been decided yet")
    approved = counts.get("APPROVE", 0) + counts.get("MODIFY", 0)
    return Measure(
        "decision_record",
        (Decimal(approved) / Decimal(n)).quantize(Decimal("0.001")),
        n,
        f"{approved} of {n} suggestions accepted or modified",
    )


def measures(db: Session, *, today: dt.date | None = None) -> list[Measure]:
    """Everything that can honestly be said about the system so far."""
    return [
        claim_accuracy(db),
        calibration(db),
        trigger_discipline(db, today=today),
        decision_record(db),
    ]


# --- remembering what was judged ------------------------------------------------------------


def record_score(
    db: Session,
    instrument,
    *,
    framework_version_id: uuid.UUID,
    ab,
    quality,
    flags: list,
    quadrant: str,
    price: Decimal | None,
    years_read: int,
    as_of: dt.date | None = None,
    today: dt.date | None = None,
):
    """Store a score, but only when it has changed since the last one.

    ⚠ Written because a score is a judgement made at a moment, with the data available then
    and the rules in force then. Recomputing it later with today's figures silently rewrites
    history — a company that scored 4 in March and 8 in September would read as 8 for both,
    and the improvement, which is the most interesting thing about it, would be invisible.

    ⚠ Only on a change. Eleven identical rows every evening would turn a history worth reading
    into a log, and what is being recorded is the movement.
    """
    from app.db.models import FrameworkScore

    as_of = as_of or today or dt.date.today()
    flags_yes = sum(1 for f in flags if f.verdict == "YES")

    previous = db.execute(
        sa.select(FrameworkScore)
        .where(FrameworkScore.instrument_id == instrument.id)
        .order_by(FrameworkScore.as_of.desc())
        .limit(1)
    ).scalar_one_or_none()

    if previous is not None:
        if previous.as_of == as_of:
            return None
        unchanged = (
            previous.ab_score == ab.total
            and previous.quality_earned == quality.earned
            and previous.quality_available == quality.available
            and previous.flags_yes == flags_yes
            and previous.quadrant == quadrant
        )
        if unchanged:
            return None

    row = FrameworkScore(
        id=uuid.uuid4(),
        instrument_id=instrument.id,
        scored_at=dt.datetime.now(dt.UTC),
        as_of=as_of,
        framework_version_id=framework_version_id,
        ab_score=ab.total,
        ab_components={c.name: str(c.points) for c in ab.components},
        quality_earned=quality.earned,
        quality_available=quality.available,
        quality_components={
            p.name: (None if p.points is None else str(p.points)) for p in quality.parts
        },
        flags_yes=flags_yes,
        flags={str(f.number): f.verdict for f in flags},
        quadrant=quadrant,
        price=price,
        years_read=years_read,
    )
    db.add(row)
    db.flush()
    return row


def score_history(db: Session, instrument_id: uuid.UUID, *, limit: int = 60) -> list:
    """How a company's three scores have moved, newest first."""
    from app.db.models import FrameworkScore

    return list(
        db.execute(
            sa.select(FrameworkScore)
            .where(FrameworkScore.instrument_id == instrument_id)
            .order_by(FrameworkScore.as_of.desc())
            .limit(limit)
        ).scalars()
    )
