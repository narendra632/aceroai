"""The six criteria for real money, and where each one stands.

⚠ **Written down in advance so they cannot be softened later.** That is the entire purpose of
this module. Committing to a standard before you know whether you will meet it is the only
version of the commitment worth anything — afterwards, every failed criterion has a reason,
and every reason is persuasive to the person who needs it to be.

⚠ **Nothing here is annualised, extrapolated or projected.** A criterion that is not met is
reported as not met, with its current value and the distance remaining. A projection of when
it *would* be met is exactly the kind of number that becomes a plan.

⚠ **Every return statistic carries its standard error**, because a number without its error
bar is the mechanism by which this system would mislead its owner. The standard error of a
Sharpe estimate over twelve monthly observations is roughly 0.35 — which means a genuinely
good strategy and a mediocre one are statistically indistinguishable over one year, and the
dashboard says so rather than letting a good-looking year read as evidence.

⚠ **Trigger discipline is not statistical.** It is the one criterion with no sample-size
defence: a system that rationalised past its own invalidation conditions even once does not
get real money, whatever the returns say.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Claim, Decision, Portfolio, Proposal, Transaction
from app.services.investments import benchmarks, returns, watching

ZERO = Decimal(0)

#: The six, pre-committed. ⚠ Constants rather than settings, deliberately. A threshold that
#: can be edited from the interface is a threshold that will be edited in the month it is
#: nearly met.
MIN_MONTHS = 12
MIN_REGIMES = 2
MIN_DECISIONS = 40
MAX_BRIER = Decimal("0.20")
MIN_CLAIM_ACCURACY = Decimal("0.60")
MIN_RESOLVED_CLAIMS = 150
REQUIRED_TRIGGER_DISCIPLINE = Decimal(1)

#: A month's index move beyond this counts as a different market condition from a flat one.
#: ⚠ Crude on purpose. A proper regime model is a v3 feature, and a placeholder that looked
#: sophisticated would invite trusting it — this one is obviously a rule of thumb, and it is
#: measured against the benchmark rather than against the portfolio so the portfolio cannot
#: define the conditions it is judged in.
REGIME_MOVE = Decimal("0.05")


@dataclass(frozen=True)
class Criterion:
    """One condition for real money, and how far off it is."""

    key: str
    question: str
    #: ⚠ None means *not yet measurable*, which is different from failing. A criterion with no
    #: sample behind it has not been failed; it has not been tested.
    met: bool | None
    value: str
    target: str
    detail: str
    #: The sample the figure rests on, where there is one.
    n: int = 0
    #: ⚠ Shown beside every return statistic. A number without its error bar is how this
    #: system would mislead its owner.
    standard_error: Decimal | None = None


@dataclass(frozen=True)
class Verdict:
    """Where the whole thing stands against what was committed to."""

    criteria: list[Criterion] = field(default_factory=list)
    generated_at: dt.datetime | None = None

    @property
    def met(self) -> int:
        return sum(1 for c in self.criteria if c.met is True)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.criteria if c.met is False)

    @property
    def untested(self) -> int:
        return sum(1 for c in self.criteria if c.met is None)

    @property
    def all_met(self) -> bool:
        return bool(self.criteria) and all(c.met is True for c in self.criteria)

    @property
    def headline(self) -> str:
        """⚠ Never encouraging. The honest summary of an early dashboard is that almost
        nothing has been tested yet, and a headline that led with the one criterion already
        met would be reporting progress where there is only time passing."""
        if self.all_met:
            return (
                "All six are met. The sane next step is still a small sleeve run in parallel "
                "for another year, not a switch."
            )
        if self.failed:
            return (
                f"{self.failed} of {len(self.criteria)} not met, {self.untested} not yet testable."
            )
        return f"{self.untested} of {len(self.criteria)} cannot be judged yet. Keep going."


# --- the six ----------------------------------------------------------------------------------


def _months_running(db: Session, user_id: uuid.UUID, today: dt.date) -> tuple[int, dt.date | None]:
    first = db.execute(
        sa.select(sa.func.min(Transaction.trade_date))
        .join(Portfolio, Transaction.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
    ).scalar_one_or_none()
    if first is None:
        return 0, None
    return (today.year - first.year) * 12 + (today.month - first.month), first


def _regimes(db: Session, start: dt.date, today: dt.date) -> int:
    """How many distinguishable market conditions the run has spanned.

    ⚠ Measured on the BENCHMARK, not on the portfolio. A portfolio that defined the conditions
    it is judged in could always claim to have seen enough of them.
    """
    days, values = benchmarks.series(db, "NIFTY50_TRI")
    if len(days) < 2:
        return 0

    seen: set[str] = set()
    cursor = start
    while cursor < today:
        nxt = min(cursor + dt.timedelta(days=30), today)
        opening = benchmarks._as_of(days, values, cursor)
        closing = benchmarks._as_of(days, values, nxt)
        if opening and closing and opening > 0:
            move = (closing - opening) / opening
            if move >= REGIME_MOVE:
                seen.add("rising")
            elif move <= -REGIME_MOVE:
                seen.add("falling")
            else:
                seen.add("flat")
        cursor = nxt
    return len(seen)


def _operating(db: Session, user_id: uuid.UUID, today: dt.date) -> Criterion:
    months, first = _months_running(db, user_id, today)
    regimes = _regimes(db, first, today) if first else 0
    met = months >= MIN_MONTHS and regimes >= MIN_REGIMES
    return Criterion(
        key="operating",
        question="Has it run long enough, across enough different markets?",
        met=met if months > 0 else None,
        value=f"{months} months, {regimes} market condition{'s' if regimes != 1 else ''}",
        target=f"{MIN_MONTHS} months, {MIN_REGIMES} conditions",
        detail=(
            "A year that was entirely one long rise proves nothing, which is why the second "
            "half of this criterion exists."
        ),
        n=months,
    )


def _decisions(db: Session, user_id: uuid.UUID) -> Criterion:
    n = db.execute(
        sa.select(sa.func.count())
        .select_from(Decision)
        .join(Proposal, Decision.proposal_id == Proposal.id)
        .join(Portfolio, Proposal.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
    ).scalar_one()
    return Criterion(
        key="decisions",
        question="Have enough decisions actually been made?",
        met=n >= MIN_DECISIONS if n else None,
        value=str(n),
        target=f"{MIN_DECISIONS}",
        detail=(
            "Forty is itself a small sample. Even met, the conclusion it supports is "
            "provisional — the serious literature wants two hundred to five hundred."
        ),
        n=n,
    )


def _calibration(db: Session) -> Criterion:
    measure = watching.calibration(db)
    brier = measure.value
    return Criterion(
        key="calibration",
        question="When it said 80%, was it right about 80% of the time?",
        met=(brier <= MAX_BRIER) if brier is not None else None,
        value=str(brier) if brier is not None else "not yet",
        target=f"Brier <= {MAX_BRIER}",
        detail=measure.detail,
        n=measure.n,
        # ⚠ A Brier score over few outcomes is itself noisy, so its own spread is shown.
        standard_error=_brier_error(brier, measure.n),
    )


def _brier_error(brier: Decimal | None, n: int) -> Decimal | None:
    """A rough spread on the Brier score. ⚠ Shown because a score of 0.19 over 22 outcomes is
    not meaningfully below 0.20, and printing it bare would suggest it is."""
    if brier is None or n < 2:
        return None
    return (Decimal("0.5") / Decimal(n).sqrt()).quantize(Decimal("0.001"))


def _claims(db: Session) -> Criterion:
    resolved = db.execute(
        sa.select(sa.func.count()).select_from(Claim).where(Claim.status.in_(("TRUE", "FALSE")))
    ).scalar_one()
    measure = watching.claim_accuracy(db)
    accuracy = measure.value
    enough = resolved >= MIN_RESOLVED_CLAIMS
    return Criterion(
        key="claims",
        question="Did the specific things the theses asserted actually happen?",
        met=(accuracy >= MIN_CLAIM_ACCURACY and enough) if (accuracy is not None) else None,
        value=str(accuracy) if accuracy is not None else "not yet",
        target=f">= {MIN_CLAIM_ACCURACY} over {MIN_RESOLVED_CLAIMS} claims",
        detail=(
            f"{resolved} resolved so far. This is the closest thing to a direct measure of "
            f"whether the reasoning works, and the one that reaches a usable sample first."
        ),
        n=resolved,
    )


def _discipline(db: Session, today: dt.date) -> Criterion:
    measure = watching.trigger_discipline(db, today=today)
    rate = measure.value
    return Criterion(
        key="discipline",
        question="When a condition it wrote came true, did it act?",
        # ⚠ No sample-size defence, and no partial credit. A system that rationalised past its
        # own invalidation conditions even once does not get real money whatever the returns
        # say — so any value below 1.00 is a failure rather than "not yet".
        met=(rate >= REQUIRED_TRIGGER_DISCIPLINE) if rate is not None else None,
        value=str(rate) if rate is not None else "nothing has fired yet",
        target="1.00, exactly",
        detail=(
            "Not statistical. This is the only criterion with no sample-size defence: one "
            "ignored condition is a disqualification, not a data point."
        ),
        n=measure.n,
    )


def _beat_the_index(db: Session, user_id: uuid.UUID, today: dt.date) -> Criterion:
    start = today - dt.timedelta(days=365)
    comparison = benchmarks.compare(db, user_id, start=start, end=today)
    book, blend = comparison.portfolio_pct, comparison.blended_pct

    if book is None or blend is None:
        return Criterion(
            key="return",
            question="Did it beat simply buying the index?",
            met=None,
            value="not yet",
            target="above the index, net of costs",
            detail=comparison.detail,
        )

    months = 12
    # ⚠ The standard error on a Sharpe estimate over twelve monthly observations, at a true
    # ratio of 1.0, is about 0.35. Printed because it is the number that says a good year and
    # a mediocre one are indistinguishable — and without it, a good year reads as evidence.
    raw = returns.standard_error_of_sharpe(Decimal(1), months)
    # ⚠ Quantized for display. An error bar printed to twenty-eight places looks like a
    # measurement rather than the rule of thumb it is, and false precision on the number whose
    # entire job is to convey imprecision would be the wrong joke to make.
    error = raw.quantize(Decimal("0.01")) if raw is not None else None

    return Criterion(
        key="return",
        question="Did it beat simply buying the index?",
        met=book > blend,
        value=f"{book} against {blend}",
        target="above the index, net of costs",
        detail=(
            "Deliberately last and least informative. Over one year the spread on a "
            f"return-quality estimate is about {error}, which means a genuinely good strategy "
            "and a mediocre one look the same."
            + (f" {comparison.caveat}" if comparison.caveat else "")
        ),
        n=months,
        standard_error=error,
    )


def assess(db: Session, user_id: uuid.UUID, *, today: dt.date | None = None) -> Verdict:
    """Where the whole thing stands against the six criteria committed to in advance."""
    today = today or dt.date.today()
    return Verdict(
        criteria=[
            _operating(db, user_id, today),
            _decisions(db, user_id),
            _calibration(db),
            _claims(db),
            _discipline(db, today),
            _beat_the_index(db, user_id, today),
        ],
        generated_at=dt.datetime.now(dt.UTC),
    )
