"""The hard rules a proposal must survive, applied by code and never by a prompt.

⚠ **This is the difference between a system and a model with opinions.** Everything else in
the decision path can be argued with — a thesis is prose, a score is a judgement about which
inputs mattered. These are not. A gate that a sufficiently persuasive argument can talk its
way past is a preference, and the entire point of writing rules down in advance is that they
bind on exactly the day you would rather they did not.

So they live here, in ordinary Python, reading stored rows. No instruction to a model
anywhere asks it to respect them, because an instruction is a request.

**A blocked proposal is still written**, with the gate that blocked it recorded, and pushed
into the shadow book. That is the only way to ever answer whether the rails are protecting or
merely obstructing — a rule whose cost is invisible is a rule nobody can evaluate.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import CorporateAction, Decision, Instrument, Proposal
from app.services.investments import corpactions, pricing

ZERO = Decimal(0)

#: Actions that put money in. Only these face the buying gates; a sale is a different question.
BUYING = frozenset({"INITIATE", "ADD", "ACCUMULATE_POOL"})

#: How long after a rejection the same name may not be raised again, unless something
#: genuinely new has happened. ⚠ Anti-nagging, and it also breaks confirmation loops: a system
#: that re-raises a rejected idea every evening will eventually catch the reader on a tired
#: day, and that is not the same as being right.
COOLING_OFF_DAYS = 14

#: The most new or added positions a month. Every real cost of activity — the transaction
#: taxes, the short-term rate being nearly double the long-term one, and the documented record
#: of active retail trading — argues for doing much less than feels natural.
MAX_PROPOSALS_PER_MONTH = 4
MAX_PER_BATCH = 3

#: Below this confidence a proposal is not worth a person's attention.
MIN_CONFIDENCE = Decimal("0.60")

#: How much of the book may sit in companies the framework does not cover.
#: ⚠ Governs what may be ADDED, never what is already held: applying it retrospectively would
#: block a position the user took before the framework existed, which is not a decision the
#: rule was ever written to make.
MAX_OFF_FRAMEWORK_SHARE = Decimal("0.05")

#: Quadrants that forbid a purchase outright. Q2 is a story without a business, which
#: collapses when the story does; Q4 is cheap for a reason, and gets cheaper.
BLOCKING_QUADRANTS = frozenset({"Q2", "Q4"})


@dataclass(frozen=True)
class GateResult:
    """One rule, and what it decided."""

    gate: str
    passed: bool
    #: True where the rule does not apply to this proposal at all — a sell facing a buying
    #: rule. ⚠ Distinct from passing: "not asked" and "asked and satisfied" are different
    #: facts, and a review counting them together would overstate how much was checked.
    not_applicable: bool
    detail: str

    @property
    def blocks(self) -> bool:
        return not self.passed and not self.not_applicable


@dataclass
class Verdict:
    """Every rule's answer, and whether the proposal may go to a person."""

    results: list[GateResult]

    @property
    def blocked_by(self) -> str | None:
        for result in self.results:
            if result.blocks:
                return result.gate
        return None

    @property
    def passed(self) -> bool:
        return self.blocked_by is None

    def as_dict(self) -> dict:
        """Frozen onto the proposal, so a review reads what was checked at the time."""
        return {
            r.gate: {
                "passed": r.passed,
                "not_applicable": r.not_applicable,
                "detail": r.detail,
            }
            for r in self.results
        }


def _ok(gate: str, detail: str) -> GateResult:
    return GateResult(gate, True, False, detail)


def _na(gate: str, detail: str) -> GateResult:
    return GateResult(gate, True, True, detail)


def _no(gate: str, detail: str) -> GateResult:
    return GateResult(gate, False, False, detail)


@dataclass
class Candidate:
    """Everything the gates need about one suggested action."""

    instrument: Instrument
    action: str
    mapping: object | None
    ab_score: object
    quality: object
    quadrant: str
    confidence: Decimal
    horizon_days: int
    triggers: list[dict]
    target_amount_inr: Decimal | None
    off_framework: bool
    #: Fraction of the book already in off-framework names, for the aggregate cap.
    off_framework_share: Decimal = ZERO
    #: How many proposals this batch has already emitted, and this month.
    in_batch: int = 0
    this_month: int = 0


def evaluate(db: Session, portfolio_id: uuid.UUID, c: Candidate) -> Verdict:
    """Run every rule. Returns all of their answers, not only the first refusal.

    ⚠ All of them, deliberately. Knowing that a proposal failed three rules rather than one
    is the difference between a near miss and a company that should not have been considered,
    and only the full set makes the shadow book worth reading.
    """
    today = dt.date.today()
    results = [
        _g1_framework(c),
        _g2_quadrant(c),
        _g3_margin_of_safety(c),
        _g4_triggers(c),
        _g6_cooling_off(db, portfolio_id, c, today),
        _g7_corporate_action(db, c),
        _g8_staleness(db, c),
        _g9_caps(c),
        _g11_confidence(c),
    ]
    return Verdict(results)


def _g1_framework(c: Candidate) -> GateResult:
    """A purchase needs an approved place in the framework, or an explicit exemption."""
    gate = "G1_framework"
    if c.action not in BUYING:
        return _na(gate, "not a purchase")
    if c.off_framework:
        if c.off_framework_share >= MAX_OFF_FRAMEWORK_SHARE:
            return _no(
                gate,
                f"off-framework holdings are already "
                f"{c.off_framework_share * 100:.1f}% of the book, at the "
                f"{MAX_OFF_FRAMEWORK_SHARE * 100:.0f}% ceiling",
            )
        return _ok(gate, "off-framework, inside the aggregate ceiling")
    if c.mapping is None or getattr(c.mapping, "approved_at", None) is None:
        return _no(
            gate,
            "its place in the framework is proposed but not agreed, so it scores nothing",
        )
    return _ok(gate, f"agreed against {getattr(c.mapping, 'b_bottleneck', '?')}")


def _g2_quadrant(c: Candidate) -> GateResult:
    """No purchase into a story without a business, or a company cheap for a reason.

    ⚠ No override, and that is the frameworks' own conclusion rather than a setting. The whole
    argument for holding both frameworks is that they refuse in different directions; a gate
    that yields to a strong enough thesis is a gate that yields exactly when the thesis is most
    persuasive, which is when it is most dangerous.
    """
    gate = "G2_quadrant"
    if c.action not in BUYING:
        return _na(gate, "not a purchase")
    if c.quadrant in BLOCKING_QUADRANTS:
        reason = "a story without a business" if c.quadrant == "Q2" else "cheap for a reason"
        return _no(gate, f"{c.quadrant}: {reason}")
    if c.quadrant in ("BORDERLINE", "UNKNOWN"):
        return _no(
            gate,
            "too little of its accounts has been read to say which box it is in, and a "
            "purchase is not made on a reading that thin",
        )
    return _ok(gate, f"{c.quadrant}")


def _g3_margin_of_safety(c: Candidate) -> GateResult:
    """Paying above a defensible worth must be said out loud, not implied."""
    gate = "G3_margin_of_safety"
    if c.action not in BUYING:
        return _na(gate, "not a purchase")
    part = next((p for p in getattr(c.quality, "parts", []) if p.name == "margin_of_safety"), None)
    if part is None or part.points is None:
        return _no(gate, "no margin of safety could be computed, so the price is unjudged")
    if part.points == ZERO:
        return _no(
            gate,
            f"the price is above a defensible worth — {part.detail}. Buying anyway means "
            "paying for growth, which this mode does not permit",
        )
    return _ok(gate, part.detail)


def _g4_triggers(c: Candidate) -> GateResult:
    """At least two machine-checkable invalidation conditions.

    ⚠ Each must be a metric, a comparison, a threshold and a deadline. "If the story changes"
    is unfalsifiable, so a position carrying it can never be shown to be wrong — which is the
    same as carrying no invalidation condition at all, dressed up as caution.
    """
    gate = "G4_invalidation"
    if c.action not in BUYING:
        return _na(gate, "not a purchase")
    usable = [
        t
        for t in c.triggers
        if t.get("metric_key")
        and t.get("comparator")
        and t.get("threshold") is not None
        and t.get("window_until")
    ]
    if len(usable) < 2:
        return _no(
            gate,
            f"{len(usable)} checkable invalidation condition(s); two are required, each a "
            "number, a comparison and a deadline",
        )
    return _ok(gate, f"{len(usable)} checkable conditions")


def _g6_cooling_off(
    db: Session, portfolio_id: uuid.UUID, c: Candidate, today: dt.date
) -> GateResult:
    """Not this name again so soon after it was turned down."""
    gate = "G6_cooling_off"
    since = dt.datetime.combine(today - dt.timedelta(days=COOLING_OFF_DAYS), dt.time(0, 0), dt.UTC)
    recent = db.execute(
        sa.select(Decision.decided_at)
        .join(Proposal, Decision.proposal_id == Proposal.id)
        .where(
            Proposal.portfolio_id == portfolio_id,
            Proposal.instrument_id == c.instrument.id,
            Decision.outcome == "REJECT",
            Decision.decided_at >= since,
        )
        .limit(1)
    ).scalar_one_or_none()
    if recent is not None:
        return _no(
            gate,
            f"turned down on {recent:%d %b}; not raised again for "
            f"{COOLING_OFF_DAYS} days unless something new has happened",
        )
    return _ok(gate, "not recently turned down")


def _g7_corporate_action(db: Session, c: Candidate) -> GateResult:
    """Nothing is proposed while a share-changing action is outstanding.

    ⚠ The highest-damage failure mode in the module. Until the ledger knows about a bonus, the
    quantity and the price are counting different things, so every figure about the holding —
    including the ones a proposal would rest on — is arithmetic over a disagreement.
    """
    gate = "G7_corporate_action"
    open_now = db.execute(
        sa.select(CorporateAction)
        .where(
            CorporateAction.instrument_id == c.instrument.id,
            CorporateAction.status.in_(corpactions.OPEN),
        )
        .limit(1)
    ).scalar_one_or_none()
    if open_now is not None:
        return _no(
            gate,
            f"a {open_now.action_type.lower()} is announced and not yet recorded, so this "
            "holding's figures are not reliable",
        )
    return _ok(gate, "no outstanding corporate action")


def _g8_staleness(db: Session, c: Candidate) -> GateResult:
    """A proposal is not made on a price nobody has checked lately."""
    gate = "G8_price_age"
    marks = pricing.latest(db, [c.instrument.id])
    mark = marks.get(c.instrument.id)
    if mark is None:
        return _no(gate, "no price has ever been observed for this company")
    if mark.is_stale:
        return _no(gate, f"the newest price is {mark.age_text} and past its limit")
    return _ok(gate, f"priced {mark.age_text}")


def _g9_caps(c: Candidate) -> GateResult:
    """How much the system may suggest, per evening and per month."""
    gate = "G9_volume"
    if c.action not in BUYING:
        return _na(gate, "not a purchase")
    if c.in_batch >= MAX_PER_BATCH:
        return _no(gate, f"{MAX_PER_BATCH} suggestions is a full evening")
    if c.this_month >= MAX_PROPOSALS_PER_MONTH:
        return _no(
            gate,
            f"{MAX_PROPOSALS_PER_MONTH} new or added positions this month is the ceiling",
        )
    return _ok(gate, f"{c.in_batch + 1} of {MAX_PER_BATCH} this evening")


def _g11_confidence(c: Candidate) -> GateResult:
    """Below the threshold, it is a research note rather than a suggestion.

    ⚠ **Buying only, and the asymmetry is the point.** This gate was action-blind, which meant
    low confidence in a company blocked the suggestion to *leave* it — so the less the system
    understood a holding, the harder it became to get out of. That is backwards on its own
    terms: confidence is a reason to commit money, and its absence is a reason to stop, never
    a reason to stay. Found when a fired invalidation condition raised an exit and this gate
    refused it.
    """
    gate = "G11_confidence"
    if c.action not in BUYING:
        return _na(gate, "reducing or leaving does not need confidence in the company")
    if c.confidence < MIN_CONFIDENCE:
        return _no(
            gate,
            f"confidence {c.confidence} is below the {MIN_CONFIDENCE} a suggestion needs",
        )
    return _ok(gate, f"confidence {c.confidence}")
