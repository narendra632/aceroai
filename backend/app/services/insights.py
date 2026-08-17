"""Reading the traces: spend, latency, reliability.

Strictly read-only. Nothing in this module or the routes above it creates, changes or
deletes anything — which is what makes the Insights page safe to open, reload, and leave
open.

Every aggregate is computed **in SQL**. Pulling a month of turns into Python to sum them
would work fine on a laptop and fall over on the 1 GB e2-micro this runs on.

A note on cost: `turns.cost_usd` was frozen when the turn was recorded, using the price
list in effect at that moment. These functions never recompute it, so a price change today
cannot rewrite last month's spend. Every figure is an ESTIMATE — both providers bill
through accounts this app never sees.
"""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.orm import Session

from app.db.models import Span, Turn

# Latency is reported as percentiles, never a mean. One 30-second turn drags an average
# far enough to hide what a typical turn feels like, and the typical turn is the product.
P50, P95 = 0.5, 0.95


def _window(stmt, user_id: uuid.UUID, since: dt.datetime | None, until: dt.datetime | None):
    stmt = stmt.where(Turn.user_id == user_id)
    if since is not None:
        stmt = stmt.where(Turn.started_at >= since)
    if until is not None:
        stmt = stmt.where(Turn.started_at < until)
    return stmt


def data_start(db: Session, user_id: uuid.UUID) -> dt.datetime | None:
    """When recording began. The page states this, so a chart never implies it has been
    watching a period it has not."""
    return db.execute(
        select(func.min(Turn.started_at)).where(Turn.user_id == user_id)
    ).scalar_one_or_none()


def summary(
    db: Session,
    user_id: uuid.UUID,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
) -> dict:
    """The headline numbers."""
    stmt = _window(
        select(
            func.count().label("calls"),
            func.coalesce(func.sum(Turn.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(Turn.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(Turn.tokens_out), 0).label("tokens_out"),
            func.coalesce(func.sum(Turn.tokens_thinking), 0).label("tokens_thinking"),
            func.sum(case((~Turn.ok, 1), else_=0)).label("failed"),
            # Only SUCCESSFUL chat turns. Two exclusions, each for its own reason:
            #
            # - background work (embeddings, extraction) has a duration nobody waits on,
            #   so including it reports a speed no human experiences;
            # - failed turns abort in milliseconds and have no first-token time at all,
            #   so leaving them in drags the duration median down while the time-to-first-
            #   token median is unaffected. Measured on real data that produced "typical
            #   reply 2393ms, first word after 2538ms" — the first word arriving after the
            #   reply finished, which is impossible and destroys trust in the whole page.
            func.percentile_cont(P50)
            .within_group(cast(Turn.duration_ms, Float))
            .filter(Turn.kind == "chat", Turn.ok)
            .label("p50_ms"),
            func.percentile_cont(P95)
            .within_group(cast(Turn.duration_ms, Float))
            .filter(Turn.kind == "chat", Turn.ok)
            .label("p95_ms"),
            func.percentile_cont(P50)
            .within_group(cast(Turn.ttft_ms, Float))
            .filter(Turn.kind == "chat", Turn.ok)
            .label("p50_ttft_ms"),
            # Turns whose model had no known price. Counted so a total can say how
            # complete it is rather than quietly understating itself.
            func.sum(case((Turn.cost_usd.is_(None), 1), else_=0)).label("unpriced"),
        ),
        user_id,
        since,
        until,
    )
    row = db.execute(stmt).one()
    calls = row.calls or 0
    return {
        "calls": calls,
        "cost_usd": Decimal(row.cost or 0),
        "tokens_in": int(row.tokens_in or 0),
        "tokens_out": int(row.tokens_out or 0),
        "tokens_thinking": int(row.tokens_thinking or 0),
        "failed": int(row.failed or 0),
        "error_rate": (float(row.failed or 0) / calls) if calls else 0.0,
        "p50_ms": int(row.p50_ms) if row.p50_ms is not None else None,
        "p95_ms": int(row.p95_ms) if row.p95_ms is not None else None,
        "p50_ttft_ms": int(row.p50_ttft_ms) if row.p50_ttft_ms is not None else None,
        "unpriced": int(row.unpriced or 0),
    }


def series(
    db: Session,
    user_id: uuid.UUID,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    tz: str = "UTC",
) -> list[dict]:
    """Spend and volume per day, split by what the call was for.

    Bucketed in the user's timezone, so "today" means their today rather than UTC's.
    """
    day = func.date(func.timezone(tz, Turn.started_at)).label("day")
    stmt = _window(
        select(
            day,
            Turn.kind,
            func.count().label("calls"),
            func.coalesce(func.sum(Turn.cost_usd), 0).label("cost"),
        ),
        user_id,
        since,
        until,
    ).group_by(day, Turn.kind)
    return [
        {"day": str(r.day), "kind": r.kind, "calls": r.calls, "cost_usd": Decimal(r.cost or 0)}
        for r in db.execute(stmt.order_by(day))
    ]


def by_model(
    db: Session,
    user_id: uuid.UUID,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
) -> list[dict]:
    """Where the money went, most expensive first."""
    stmt = _window(
        select(
            Turn.provider,
            Turn.model,
            func.count().label("calls"),
            func.coalesce(func.sum(Turn.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(Turn.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(Turn.tokens_out), 0).label("tokens_out"),
        ),
        user_id,
        since,
        until,
    ).group_by(Turn.provider, Turn.model)
    rows = db.execute(stmt.order_by(func.coalesce(func.sum(Turn.cost_usd), 0).desc())).all()
    return [
        {
            "provider": r.provider,
            "model": r.model,
            "calls": r.calls,
            "cost_usd": Decimal(r.cost or 0),
            "tokens_in": int(r.tokens_in or 0),
            "tokens_out": int(r.tokens_out or 0),
        }
        for r in rows
    ]


def by_provider(
    db: Session,
    user_id: uuid.UUID,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
) -> list[dict]:
    """Providers side by side — cost, speed and reliability.

    This is what turns the provider switch in Settings from a hunch into a decision. Only
    chat turns are compared: embeddings are pinned to one provider regardless of the
    choice, so including them would blame Google for work the setting never touched.
    """
    stmt = (
        _window(
            select(
                Turn.provider,
                func.count().label("calls"),
                func.coalesce(func.sum(Turn.cost_usd), 0).label("cost"),
                # Successful turns only, for the same reason as `summary`.
                func.percentile_cont(P50)
                .within_group(cast(Turn.duration_ms, Float))
                .filter(Turn.ok)
                .label("p50_ms"),
                func.percentile_cont(P50)
                .within_group(cast(Turn.ttft_ms, Float))
                .filter(Turn.ok)
                .label("p50_ttft_ms"),
                func.sum(case((~Turn.ok, 1), else_=0)).label("failed"),
            ),
            user_id,
            since,
            until,
        )
        .where(Turn.kind == "chat")
        .group_by(Turn.provider)
    )
    out = []
    for r in db.execute(stmt.order_by(Turn.provider)):
        calls = r.calls or 0
        out.append(
            {
                "provider": r.provider,
                "calls": calls,
                "cost_usd": Decimal(r.cost or 0),
                "cost_per_call": (Decimal(r.cost or 0) / calls) if calls else Decimal(0),
                "p50_ms": int(r.p50_ms) if r.p50_ms is not None else None,
                "p50_ttft_ms": int(r.p50_ttft_ms) if r.p50_ttft_ms is not None else None,
                "error_rate": (float(r.failed or 0) / calls) if calls else 0.0,
            }
        )
    return out


def errors(
    db: Session,
    user_id: uuid.UUID,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
) -> list[dict]:
    """What actually goes wrong, most common first. A rate limit and a billing problem
    return the same status code from most providers, so telling them apart is the
    difference between waiting and fixing an account."""
    stmt = (
        _window(
            select(Turn.error_type, func.count().label("count")),
            user_id,
            since,
            until,
        )
        .where(~Turn.ok)
        .group_by(Turn.error_type)
    )
    return [
        {"error_type": r.error_type or "unknown", "count": r.count}
        for r in db.execute(stmt.order_by(func.count().desc()))
    ]


def recent(
    db: Session,
    user_id: uuid.UUID,
    *,
    limit: int = 50,
    kind: str | None = None,
) -> list[Turn]:
    stmt = select(Turn).where(Turn.user_id == user_id)
    if kind:
        stmt = stmt.where(Turn.kind == kind)
    return list(db.execute(stmt.order_by(Turn.started_at.desc()).limit(limit)).scalars().all())


def turn_with_spans(
    db: Session, user_id: uuid.UUID, turn_id: uuid.UUID
) -> tuple[Turn, list[Span]] | None:
    """One turn and its stages, in order — the data behind the waterfall."""
    turn = db.execute(
        select(Turn).where(Turn.id == turn_id, Turn.user_id == user_id)
    ).scalar_one_or_none()
    if turn is None:
        return None
    spans = list(
        db.execute(select(Span).where(Span.turn_id == turn.id).order_by(Span.seq)).scalars().all()
    )
    return turn, spans
