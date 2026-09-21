"""Looking backwards, on a schedule.

Saturday morning no market is open and nothing is urgent, so the system does the thing it
cannot do on a weekday: it asks whether any of this is working.

⚠ **Assembled by code, never written by a model.** Everywhere else in this module a model is
forbidden from producing a number, and a review is almost entirely numbers. A paragraph
summarising them would be the single place in the design where a figure could be restated
wrongly with nothing to check it against — so the review is a structure of facts, each one
read from a row that already exists, and the interface renders it.

⚠ **Every measure withholds itself below its sample size.** A hit rate over six reads exactly
like one over six hundred, and a review that showed both the same way would teach its reader
to trust numbers that mean nothing. "Not yet" appears a great deal in the first year, and that
is the review working rather than failing.

⚠ **The parts that look bad are not softened.** A queue nobody has cleared, a budget nothing
was spent from, a condition that fired and was ignored — these are the entries worth having,
and a review that led with the good week would be a report rather than a record.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import asdict, is_dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Decision, InvalidationTrigger, Portfolio, Proposal, Review, User
from app.services.investments import benchmarks, books, reading, watching

#: How close to its threshold a condition has to be before a review mentions it. ⚠ Reported
#: because a condition at 97% of its threshold is the most useful thing a weekly review can
#: contain, and it is invisible to a system that only reports firings.
NEAR_THRESHOLD = Decimal("0.95")

#: A queue line older than this is called out. ⚠ Not a deadline — an idea can be worth waiting
#: on — but a queue nobody clears has stopped being read, and nothing else would notice.
STALE_QUEUE_DAYS = 21

KINDS = ("WEEKLY", "MONTHLY", "QUARTERLY")


def period_for(kind: str, end: dt.date) -> tuple[dt.date, dt.date]:
    """The window a review of this kind covers, ending on `end`."""
    if kind == "WEEKLY":
        return end - dt.timedelta(days=6), end
    if kind == "MONTHLY":
        first = end.replace(day=1)
        return first, end
    if kind == "QUARTERLY":
        quarter_first_month = 3 * ((end.month - 1) // 3) + 1
        return end.replace(month=quarter_first_month, day=1), end
    raise ValueError(f"unknown review kind {kind!r}")


def _plain(value):
    """JSON-safe, and Decimals as strings.

    ⚠ Money and scores cross as text. `json` would turn a Decimal into a float on the way in,
    and 4.1 stored as 4.0999999999999996 in a record nobody can correct afterwards is exactly
    the failure this module spends its effort avoiding.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


# --- the pieces ------------------------------------------------------------------------------


def decisions_in(db: Session, user_id: uuid.UUID, start: dt.date, end: dt.date) -> dict:
    """What was approved, turned down or changed — and why, in your own words.

    ⚠ The reasons are carried through verbatim. They are the data that eventually says what
    kinds of suggestion keep being refused, and a count without them says nothing at all.
    """
    rows = db.execute(
        sa.select(Decision, Proposal)
        .join(Proposal, Decision.proposal_id == Proposal.id)
        .join(Portfolio, Proposal.portfolio_id == Portfolio.id)
        .where(
            Portfolio.user_id == user_id,
            sa.func.date(Decision.decided_at) >= start,
            sa.func.date(Decision.decided_at) <= end,
        )
        .order_by(Decision.decided_at)
    ).all()

    counts: dict[str, int] = {}
    listed = []
    for decision, proposal in rows:
        counts[decision.outcome] = counts.get(decision.outcome, 0) + 1
        listed.append(
            {
                "outcome": decision.outcome,
                "action": proposal.action,
                "thesis": (proposal.thesis or "")[:200],
                "reason": decision.reason_text,
                "on": decision.decided_at.date(),
            }
        )
    return {"counts": counts, "decisions": listed}


def blocked_in(db: Session, user_id: uuid.UUID, start: dt.date, end: dt.date) -> list[dict]:
    """Suggestions the rules refused before anyone saw them.

    ⚠ Reported, because the rails are measured too. A refusal nobody is shown is a rule nobody
    can ever ask whether it was protecting or merely obstructing.
    """
    rows = db.execute(
        sa.select(Proposal)
        .join(Portfolio, Proposal.portfolio_id == Portfolio.id)
        .where(
            Portfolio.user_id == user_id,
            Proposal.status == "BLOCKED",
            sa.func.date(Proposal.created_at) >= start,
            sa.func.date(Proposal.created_at) <= end,
        )
        .order_by(Proposal.created_at)
    ).scalars()
    return [{"action": row.action, "blocked_by": row.blocked_by} for row in rows]


def approaching(db: Session, *, today: dt.date | None = None) -> list[dict]:
    """Conditions close to firing but not yet fired.

    ⚠ The most useful thing a weekly review carries, and invisible to anything that reports
    only firings. A condition at 97% of its threshold is a week's warning.
    """
    today = today or dt.date.today()
    out = []
    armed = db.execute(
        sa.select(InvalidationTrigger).where(InvalidationTrigger.status == "ARMED")
    ).scalars()

    for trigger in armed:
        value = watching.current_value(db, trigger.instrument_id, trigger.metric_key)
        if value is None or not trigger.threshold:
            continue
        # How far along the way to its threshold the metric has travelled, in the direction
        # the condition cares about.
        ratio = (
            value / trigger.threshold
            if trigger.comparator in ("GT", "GTE", "CROSSES_ABOVE")
            else trigger.threshold / value
            if value
            else Decimal(0)
        )
        if ratio >= NEAR_THRESHOLD:
            out.append(
                {
                    "description": trigger.description,
                    "metric": trigger.metric_key,
                    "value": value,
                    "threshold": trigger.threshold,
                    "due_by": trigger.window_until,
                }
            )
    return out


def queue_health(db: Session) -> dict:
    """How the research queue is doing, including the part nobody wants to look at."""
    lines = reading.queue(db)
    stale = [line for line in lines if line.age_days >= STALE_QUEUE_DAYS]
    return {
        "waiting": len(lines),
        "oldest_days": max((line.age_days for line in lines), default=0),
        # ⚠ Named, not counted. "Three have been waiting a month" prompts nothing; naming them
        # is what turns a statistic into a decision.
        "stale": [{"symbol": line.symbol, "age_days": line.age_days} for line in stale],
    }


def budget_state(db: Session, user_id: uuid.UUID, start: dt.date, end: dt.date) -> dict:
    """What was deployable and what was deployed.

    ⚠ Unspent is a legitimate outcome and is reported without apology. The budget is a ceiling
    rather than a target, and a review that framed unspent money as a shortfall would be
    arguing for activity — which is the one bias this whole design is built against.
    """
    mirror = books.get(db, user_id, "MIRROR")
    budget = (mirror.monthly_budget_inr if mirror else None) or Decimal(30000)
    spent = db.execute(
        sa.select(sa.func.coalesce(sa.func.sum(Proposal.target_amount_inr), 0))
        .join(Decision, Decision.proposal_id == Proposal.id)
        .join(Portfolio, Proposal.portfolio_id == Portfolio.id)
        .where(
            Portfolio.user_id == user_id,
            Decision.outcome.in_(("APPROVE", "MODIFY")),
            sa.func.date(Decision.decided_at) >= start,
            sa.func.date(Decision.decided_at) <= end,
        )
    ).scalar_one() or Decimal(0)
    return {
        "budget_inr": budget,
        "committed_inr": Decimal(spent),
        "unspent_inr": budget - Decimal(spent),
    }


def books_state(db: Session, user_id: uuid.UUID) -> dict:
    """Every book at the same prices at the same moment."""
    comparison = books.compare(db, user_id)
    return {
        "readable": comparison.readable,
        "as_of": comparison.as_of,
        "lines": [
            {
                "kind": line.kind,
                "name": line.name,
                "invested_inr": line.invested_inr,
                "value_inr": line.value_inr,
                "gain_pct": line.gain_pct,
                "positions": line.positions,
                "is_complete": line.is_complete,
            }
            for line in comparison.lines
        ],
        "unaided": books.unaided(db, user_id),
    }


def sources_state(db: Session, *, today: dt.date | None = None) -> list[dict]:
    """What each source named, and whether its calls worked out.

    ⚠ `named` counts everything, including what was never looked at. Scoring a source on the
    ideas that were acted on measures the reader's filter and turns 2.5% into 33%.
    """
    return [
        {
            "source": row.source,
            "trust_tier": row.trust_tier,
            "named": row.named,
            "directional": row.directional,
            "scored": row.scored,
            "pending": row.pending,
            "became_proposals": row.became_proposals,
            "hit_rate": row.hit_rate.value,
            "n": row.hit_rate.n,
            "detail": row.hit_rate.detail,
        }
        for row in reading.attributions(db, today=today)
    ]


def benchmark_state(db: Session, user_id: uuid.UUID, start: dt.date, end: dt.date) -> dict:
    """The book against what could have been bought instead, over this same window.

    ⚠ The caveat travels with the figures rather than instead of them. Crypto and funds are in
    the portfolio's own return and no index stands in for them, so when they are a large share
    the two sides measure different things — and quietly excluding them would be picking the
    flattering subset.
    """
    comparison = benchmarks.compare(db, user_id, start=start, end=end)
    return {
        "readable": comparison.readable,
        "portfolio_pct": comparison.portfolio_pct,
        "blended_pct": comparison.blended_pct,
        "weights": comparison.weights,
        "non_equity_share": comparison.non_equity_share,
        "caveat": comparison.caveat,
        "detail": comparison.detail,
        "lines": [
            {
                "key": line.key,
                "name": line.name,
                "proxy_for": line.proxy_for,
                "change_pct": line.change_pct,
                "detail": line.detail,
            }
            for line in comparison.lines
        ],
    }


# --- putting it together -----------------------------------------------------------------------


def _headline(kind: str, content: dict) -> str:
    """One line that does not flatter.

    ⚠ It leads with what needs doing, not with the week's return. A review whose first line is
    a number invites reading only that number, and the numbers are the part that means least
    this early.
    """
    decisions = content["decisions"]["counts"]
    taken = sum(decisions.values())
    queue = content["queue"]["waiting"]
    near = len(content["approaching"])
    unspent = content["budget"]["unspent_inr"]

    parts = []
    if taken:
        parts.append(f"{taken} decision{'s' if taken != 1 else ''}")
    else:
        parts.append("no decisions")
    if near:
        parts.append(f"{near} condition{'s' if near != 1 else ''} near firing")
    if queue:
        parts.append(f"{queue} waiting to be looked at")
    if unspent > 0:
        parts.append(f"₹{unspent:,.0f} unspent")
    return f"{kind.title()} review: " + ", ".join(parts) + "."


def assemble(
    db: Session,
    user_id: uuid.UUID,
    kind: str,
    *,
    end: dt.date | None = None,
) -> tuple[dict, str, dt.date, dt.date]:
    """Everything the review says, as facts. Nothing is written here."""
    end = end or dt.date.today()
    start, end = period_for(kind, end)

    content: dict = {
        "kind": kind,
        "period": {"start": start, "end": end},
        "decisions": decisions_in(db, user_id, start, end),
        "blocked": blocked_in(db, user_id, start, end),
        "approaching": approaching(db, today=end),
        "queue": queue_health(db),
        "budget": budget_state(db, user_id, start, end),
        "books": books_state(db, user_id),
        # ⚠ Over the review's own window, not a rolling year. A weekly review comparing a
        # twelve-month portfolio figure against a seven-day benchmark would be comparing two
        # different spans and reading like one.
        "benchmarks": benchmark_state(db, user_id, start, end),
        # ⚠ Every one of these withholds itself below its sample size, and says so in its own
        # words. "Not yet" is the honest state for most of the first year.
        "measures": [
            {"name": m.name, "value": m.value, "n": m.n, "detail": m.detail}
            for m in watching.measures(db, today=end)
        ],
    }

    if kind in ("MONTHLY", "QUARTERLY"):
        # ⚠ Monthly and up only. Source attribution over one week is noise wearing a number,
        # and showing it weekly would train its reader to read noise.
        content["sources"] = sources_state(db, today=end)

    return content, _headline(kind, content), start, end


def write(
    db: Session,
    user: User,
    kind: str,
    *,
    end: dt.date | None = None,
) -> Review | None:
    """Assemble and store one review. `None` if this period already has one.

    ⚠ Not an error when it exists. A catch-up run after a restart reaching Saturday's review
    twice must leave the first one alone — a review that could be written twice is one whose
    two copies will eventually disagree, and neither would be wrong on its face.
    """
    content, headline, start, period_end = assemble(db, user.id, kind, end=end)

    existing = db.execute(
        sa.select(Review).where(
            Review.user_id == user.id, Review.kind == kind, Review.period_end == period_end
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None

    row = Review(
        id=uuid.uuid4(),
        user_id=user.id,
        kind=kind,
        period_start=start,
        period_end=period_end,
        generated_at=dt.datetime.now(dt.UTC),
        content=_plain(content),
        headline=headline,
    )
    db.add(row)
    db.flush()
    return row


def recent(db: Session, user_id: uuid.UUID, *, limit: int = 12) -> list[Review]:
    return list(
        db.execute(
            sa.select(Review)
            .where(Review.user_id == user_id)
            .order_by(Review.period_end.desc(), Review.kind)
            .limit(limit)
        ).scalars()
    )
