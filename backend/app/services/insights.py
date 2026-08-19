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
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import DailyUsage, Span, Turn

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


def _boundary(db: Session, user_id: uuid.UUID) -> dt.date | None:
    """The last day the rollup covers. Up to and including it, `daily_usage` is the source;
    after it, live `turns` are. None means nothing has been rolled up yet.

    Deriving the split from what the rollup ACTUALLY holds — rather than from the retention
    window — is what makes it both gap-free and duplicate-free:

      * a day in both tables is read once, from the rollup;
      * a day that has aged past the retention window but has not been pruned yet is still
        counted, because the boundary follows the rollup rather than the calendar.

    An earlier version used the retention cutoff as a fixed date. Turns that had aged past
    it but not yet been swept vanished from every total until a sweep happened to run.
    Caught by `test_spend_history_survives_pruning`.
    """
    return db.execute(
        select(func.max(DailyUsage.day)).where(DailyUsage.user_id == user_id)
    ).scalar_one_or_none()


def _usage(db: Session, user_id: uuid.UUID, since: dt.datetime | None, until: dt.datetime | None):
    """Every model call in the window as day / kind / provider / model plus totals.

    Live turns inside the retention window, UNION the daily rollup outside it, so the spend
    history survives pruning. Aggregates build on this rather than on `turns` directly.

    What is NOT here, and cannot be: latency percentiles and error types. A median does not
    re-derive from daily medians, and error kinds are a "what is going wrong lately"
    question. Both stay on the live table and are therefore bounded by
    `turn_retention_days` — stated in the docstrings that use them.
    """
    tz = settings.app_timezone
    boundary = _boundary(db, user_id)
    day = func.date(func.timezone(tz, Turn.started_at))
    provider = func.coalesce(Turn.provider, "unknown")
    model = func.coalesce(Turn.model, "unknown")

    live_where = [Turn.user_id == user_id]
    if boundary is not None:
        live_where.append(day > boundary)
    if since is not None:
        live_where.append(Turn.started_at >= since)
    if until is not None:
        live_where.append(Turn.started_at < until)

    live = (
        select(
            day.label("day"),
            Turn.kind.label("kind"),
            provider.label("provider"),
            model.label("model"),
            func.count().label("calls"),
            func.sum(case((~Turn.ok, 1), else_=0)).label("failed"),
            func.sum(case((Turn.cost_usd.is_(None), 1), else_=0)).label("unpriced"),
            func.coalesce(func.sum(Turn.cost_usd), 0).label("cost_usd"),
            func.coalesce(func.sum(Turn.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(Turn.tokens_out), 0).label("tokens_out"),
            func.coalesce(func.sum(Turn.tokens_thinking), 0).label("tokens_thinking"),
        )
        .where(*live_where)
        .group_by(day, Turn.kind, provider, model)
    )

    # Whole days only on this side — that is the granularity the rollup has. It matters
    # only for a window whose edge falls beyond the retention boundary, where per-second
    # precision no longer exists to be had.
    rolled_where = [DailyUsage.user_id == user_id]
    if boundary is not None:
        rolled_where.append(DailyUsage.day <= boundary)
    else:
        rolled_where.append(sa.false())  # nothing rolled up yet
    if since is not None:
        rolled_where.append(DailyUsage.day >= since.astimezone(ZoneInfo(tz)).date())
    if until is not None:
        rolled_where.append(DailyUsage.day < until.astimezone(ZoneInfo(tz)).date())

    rolled = select(
        DailyUsage.day,
        DailyUsage.kind,
        DailyUsage.provider,
        DailyUsage.model,
        DailyUsage.calls,
        DailyUsage.failed,
        DailyUsage.unpriced,
        DailyUsage.cost_usd,
        DailyUsage.tokens_in,
        DailyUsage.tokens_out,
        DailyUsage.tokens_thinking,
    ).where(*rolled_where)

    return live.union_all(rolled).subquery()


def spend_since(db: Session, user_id: uuid.UUID, since: dt.datetime) -> Decimal:
    """Total estimated spend from `since` to now — every call, not just chat.

    Built on `_usage` like every other figure, so the budget counts the same dollars the
    page shows and keeps counting them after old turns are pruned. A second definition of
    "what this cost" would eventually disagree with the first.
    """
    u = _usage(db, user_id, since, None)
    total = db.execute(select(func.coalesce(func.sum(u.c.cost_usd), 0))).scalar_one()
    return Decimal(total or 0)


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
    """The headline numbers.

    Counts and money come from `_usage`, so they survive pruning. The latency percentiles
    below cannot be rolled up and are therefore only available for the last
    `turn_retention_days`.
    """
    u = _usage(db, user_id, since, until)
    totals = db.execute(
        select(
            func.coalesce(func.sum(u.c.calls), 0).label("calls"),
            func.coalesce(func.sum(u.c.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(u.c.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(u.c.tokens_out), 0).label("tokens_out"),
            func.coalesce(func.sum(u.c.tokens_thinking), 0).label("tokens_thinking"),
            func.coalesce(func.sum(u.c.failed), 0).label("failed"),
            func.coalesce(func.sum(u.c.unpriced), 0).label("unpriced"),
        )
    ).one()

    stmt = _window(
        select(
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
        ),
        user_id,
        since,
        until,
    )
    row = db.execute(stmt).one()
    calls = int(totals.calls or 0)
    failed = int(totals.failed or 0)
    return {
        "calls": calls,
        "cost_usd": Decimal(totals.cost or 0),
        "tokens_in": int(totals.tokens_in or 0),
        "tokens_out": int(totals.tokens_out or 0),
        "tokens_thinking": int(totals.tokens_thinking or 0),
        "failed": failed,
        "error_rate": (failed / calls) if calls else 0.0,
        "p50_ms": int(row.p50_ms) if row.p50_ms is not None else None,
        "p95_ms": int(row.p95_ms) if row.p95_ms is not None else None,
        "p50_ttft_ms": int(row.p50_ttft_ms) if row.p50_ttft_ms is not None else None,
        "unpriced": int(totals.unpriced or 0),
    }


def series(
    db: Session,
    user_id: uuid.UUID,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
) -> list[dict]:
    """Spend and volume per day, split by what the call was for.

    Always bucketed in `settings.app_timezone`, so "today" means the user's today rather
    than UTC's. Not a parameter: once a day has been rolled up its boundaries are fixed,
    and re-bucketing history on request would be a promise this cannot keep.
    """
    u = _usage(db, user_id, since, until)
    stmt = (
        select(
            u.c.day,
            u.c.kind,
            func.sum(u.c.calls).label("calls"),
            func.coalesce(func.sum(u.c.cost_usd), 0).label("cost"),
        )
        .group_by(u.c.day, u.c.kind)
        .order_by(u.c.day)
    )
    return [
        {"day": str(r.day), "kind": r.kind, "calls": int(r.calls), "cost_usd": Decimal(r.cost or 0)}
        for r in db.execute(stmt)
    ]


def by_model(
    db: Session,
    user_id: uuid.UUID,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
) -> list[dict]:
    """Where the money went, most expensive first."""
    u = _usage(db, user_id, since, until)
    cost = func.coalesce(func.sum(u.c.cost_usd), 0)
    stmt = (
        select(
            u.c.provider,
            u.c.model,
            func.sum(u.c.calls).label("calls"),
            cost.label("cost"),
            func.coalesce(func.sum(u.c.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(u.c.tokens_out), 0).label("tokens_out"),
        )
        .group_by(u.c.provider, u.c.model)
        .order_by(cost.desc())
    )
    rows = db.execute(stmt).all()
    return [
        {
            "provider": r.provider,
            "model": r.model,
            "calls": r.calls,
            "cost_usd": Decimal(r.cost or 0),
            "tokens_in": int(r.tokens_in or 0),
            "tokens_out": int(r.tokens_out or 0),
            # The embedding model is not selectable: every stored memory was written by it,
            # and swapping it would make them unreadable. Flagged so the interface can mark
            # the row rather than explaining the exception in prose underneath.
            "pinned": r.model == settings.embed_model,
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

    Two queries, because they answer to different tables. Cost and volume come from
    `_usage` and outlive pruning; the speed columns can only come from live turns, so they
    go blank for a provider whose calls all predate the retention window.
    """
    u = _usage(db, user_id, since, until)
    money = (
        select(
            u.c.provider,
            func.sum(u.c.calls).label("calls"),
            func.coalesce(func.sum(u.c.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(u.c.failed), 0).label("failed"),
        )
        .where(u.c.kind == "chat")
        .group_by(u.c.provider)
        .order_by(u.c.provider)
    )
    speed = {
        r.provider: r
        for r in db.execute(
            _window(
                select(
                    Turn.provider,
                    # Successful turns only, for the same reason as `summary`.
                    func.percentile_cont(P50)
                    .within_group(cast(Turn.duration_ms, Float))
                    .filter(Turn.ok)
                    .label("p50_ms"),
                    func.percentile_cont(P50)
                    .within_group(cast(Turn.ttft_ms, Float))
                    .filter(Turn.ok)
                    .label("p50_ttft_ms"),
                ),
                user_id,
                since,
                until,
            )
            .where(Turn.kind == "chat")
            .group_by(Turn.provider)
        )
    }

    out = []
    for r in db.execute(money):
        calls = int(r.calls or 0)
        latency = speed.get(r.provider)
        p50 = getattr(latency, "p50_ms", None)
        ttft = getattr(latency, "p50_ttft_ms", None)
        out.append(
            {
                "provider": r.provider,
                "calls": calls,
                "cost_usd": Decimal(r.cost or 0),
                "cost_per_call": (Decimal(r.cost or 0) / calls) if calls else Decimal(0),
                "p50_ms": int(p50) if p50 is not None else None,
                "p50_ttft_ms": int(ttft) if ttft is not None else None,
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
    difference between waiting and fixing an account.

    Live turns only. The rollup keeps how many calls failed but not what they failed with,
    because "what is breaking" is a question about now — and a list of error kinds from
    fourteen months ago would cost storage to answer nobody's question.
    """
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
