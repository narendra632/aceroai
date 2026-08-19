"""Keeping the traces from outgrowing the app they observe.

`turns` and `spans` are written on every model call — including the ones nobody sees, so
roughly four turns and thirty-odd spans per message. On a 1 GB / 10 GB VM that is
unbounded growth in the tables least worth keeping forever. Nobody asks about the latency
of one turn from eight months ago; plenty of people ask what they spent in March.

So there are three tiers:

    spans        pruned after `span_retention_days`   (the per-stage waterfall)
    turns        pruned after `turn_retention_days`   (one row per model call)
    daily_usage  kept forever                          (one row per day per model)

The order matters and is enforced in `sweep`: a day is rolled up **before** the turns
behind it can be deleted. Getting that backwards silently destroys history.

Everything here is idempotent. Running the sweep twice in a row changes nothing the second
time, which is what makes it safe to trigger opportunistically rather than from a
scheduler.

TODO(scheduled-jobs): when the scheduler lands this becomes a proper nightly job and
`maybe_sweep` can go away. Until then it runs off the back of a real turn.
"""

import datetime as dt
import logging
import threading
from zoneinfo import ZoneInfo

from sqlalchemy import case, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import DailyUsage, Span, Turn

log = logging.getLogger(__name__)

# The columns the rollup carries, and the aggregate that produces each. Percentiles are
# deliberately absent: a median cannot be re-derived from daily medians, so latency
# distribution is only available while the turns themselves are.
_ROLLUP_COLUMNS = (
    "calls",
    "failed",
    "unpriced",
    "cost_usd",
    "tokens_in",
    "tokens_out",
    "tokens_thinking",
)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def today_local() -> dt.date:
    """Today in the timezone the Insights page draws, which is the timezone days are
    bucketed in. Rolling up in UTC and displaying in Asia/Kolkata would leave every total
    correct and every daily figure wrong."""
    return dt.datetime.now(_tz()).date()


def turn_cutoff(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.UTC)
    return now - dt.timedelta(days=settings.turn_retention_days)


def span_cutoff(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.UTC)
    return now - dt.timedelta(days=settings.span_retention_days)


def rollup(db: Session, *, through: dt.date | None = None) -> int:
    """Fold complete days of `turns` into `daily_usage`. Returns days written.

    Only days that have *finished* are rolled up — today is still accumulating, and a
    partial total written now would be wrong until the next sweep overwrote it. The
    Insights page reads today from the live turns anyway.

    Idempotent by construction: the insert upserts on the day key, so re-running recomputes
    the same numbers rather than adding to them. That matters because this runs
    opportunistically and may fire twice for the same day.
    """
    through = through or today_local()  # exclusive: today is not complete
    day = func.date(func.timezone(settings.app_timezone, Turn.started_at)).label("day")
    # Bound to names and reused, never re-spelled. Writing the same coalesce twice makes
    # SQLAlchemy emit two different bind parameters, and Postgres then refuses the GROUP BY
    # because the two expressions are not textually identical.
    provider = func.coalesce(Turn.provider, "unknown")
    model = func.coalesce(Turn.model, "unknown")

    source = (
        select(
            # Generated in SQL, not by the ORM. An INSERT..SELECT has no per-row Python
            # hook, so a client-side default becomes ONE bound parameter reused for every
            # row — a duplicate primary key the moment a sweep covers two days.
            func.gen_random_uuid().label("id"),
            Turn.user_id.label("user_id"),
            day,
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
        .where(day < through)
        .group_by(Turn.user_id, day, Turn.kind, provider, model)
    )

    stmt = insert(DailyUsage).from_select(
        ["id", "user_id", "day", "kind", "provider", "model", *_ROLLUP_COLUMNS], source
    )
    stmt = stmt.on_conflict_do_update(
        constraint="daily_usage_key",
        set_={c: getattr(stmt.excluded, c) for c in _ROLLUP_COLUMNS},
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0


def prune_spans(db: Session, *, before: dt.datetime | None = None) -> int:
    """Drop per-stage detail for old turns, keeping the turns themselves."""
    before = before or span_cutoff()
    old = select(Turn.id).where(Turn.started_at < before)
    result = db.execute(delete(Span).where(Span.turn_id.in_(old)))
    db.commit()
    return result.rowcount or 0


def prune_turns(db: Session, *, before: dt.datetime | None = None) -> int:
    """Drop old turns. Spans cascade.

    Refuses to delete anything the rollup has not already covered. Without this guard an
    ordering mistake — or a rollup that failed and was swallowed — would take the history
    with it, and there is no backup to recover from.
    """
    before = before or turn_cutoff()
    day = func.date(func.timezone(settings.app_timezone, Turn.started_at))
    # Per-day, not a global high-water mark. A turn is deleted only if ITS OWN day is in
    # the rollup, so a rollup that failed, was skipped, or never covered this stretch
    # cannot take the history with it. An earlier version compared one max(day) against the
    # cutoff and refused every legitimate prune when the only data was old.
    covered = select(DailyUsage.id).where(DailyUsage.user_id == Turn.user_id, DailyUsage.day == day)
    result = db.execute(delete(Turn).where(Turn.started_at < before, covered.exists()))
    db.commit()
    return result.rowcount or 0


def sweep(db: Session) -> dict[str, int]:
    """Roll up, then prune — in that order, always."""
    days = rollup(db)
    spans = prune_spans(db)
    turns = prune_turns(db)
    if spans or turns:
        log.info(
            "retention: rolled up %d day-rows, pruned %d spans and %d turns", days, spans, turns
        )
    return {"rolled_up": days, "spans_pruned": spans, "turns_pruned": turns}


# --- opportunistic triggering -------------------------------------------------------

_lock = threading.Lock()
_last_run: dt.date | None = None


def maybe_sweep(db: Session) -> bool:
    """Run the sweep at most once per local day, per process. Returns whether it ran.

    Deliberately not on a timer and not on every turn: the work is trivial but pointless to
    repeat, and a background thread would be a second thing to reason about at startup. The
    state is in memory, so a restart can cause one extra sweep — harmless, because the
    sweep is idempotent.

    Never raises. This runs behind a reply that has already been sent, and housekeeping
    must not be able to turn a delivered answer into an error.
    """
    global _last_run
    today = today_local()
    with _lock:
        if _last_run == today:
            return False
        _last_run = today
    try:
        # Housekeeping must never WAIT. The prunes take row locks on `turns` and `spans`,
        # and this runs while real requests hold their own transactions on the same tables;
        # without a timeout a contended DELETE would block a threadpool worker indefinitely.
        # Giving up costs a day of pruning — the sweep is idempotent and catches up
        # tomorrow — which is a far better failure than a stuck worker.
        db.execute(text("SET lock_timeout = '3s'"))
        db.execute(text("SET statement_timeout = '60s'"))
        db.commit()
        sweep(db)
        return True
    except Exception:
        log.warning("retention sweep failed; nothing else is affected", exc_info=True)
        db.rollback()
        return False
    finally:
        # The session is closed by the caller, but a pooled connection would otherwise
        # carry these settings into whatever runs next.
        try:
            db.execute(text("RESET lock_timeout"))
            db.execute(text("RESET statement_timeout"))
            db.commit()
        except Exception:  # noqa: BLE001 - a dead connection has nothing to reset
            db.rollback()
