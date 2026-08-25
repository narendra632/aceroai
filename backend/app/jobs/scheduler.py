"""The ticker.

APScheduler holds **exactly one job**: call `tick` every few minutes. Everything about
*what* runs and *whether it already ran* lives in `runner.py` and the `job_runs` table.

That is the decision worth understanding here. Registering six APScheduler jobs would give
the scheduler its own opinion about what has happened, next to the database's opinion — two
sources of truth that can disagree, and every test would then need a live event loop. With
one tick, APScheduler is reduced to what it is genuinely good at in this application:
parsing cron expressions with timezone awareness, and running a drift-free timer that shuts
down cleanly.

The consequence is that `tick(db, user, now=...)` is a plain function of its arguments, and
the entire scheduling system can be tested without starting anything.
"""

import datetime as dt
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from app.config import settings
from app.db.models import User
from app.db.session import SessionLocal
from app.jobs import runner

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

#: When the ticker last completed a pass. Read by `services/vitals` to answer the one
#: question no other part of the system can: **is scheduled work still being attempted?**
#:
#: Deliberately in memory rather than a row. `job_runs` cannot answer it — a row is written
#: only when an occurrence actually fires, and the gap between the 21:00 nudge and the 03:15
#: sweep is six hours of healthy silence. Reading "last job run" as a heartbeat would report
#: a dead scheduler every single night.
#:
#: A heartbeat table would work and would cost a write every tick — roughly 105,000 rows a
#: year whose entire purpose is to be overwritten. In-process costs nothing and catches the
#: failure that actually matters: the APScheduler thread dying while uvicorn keeps serving
#: requests, which produces no error anywhere. If the whole process dies instead, Docker
#: restarts it and `uptime` says so.
#:
#: `None` after a restart is therefore correct information, not lost information: this
#: process has not ticked yet. Valid because the API runs as a single uvicorn process — the
#: same assumption the entire job design already rests on.
_last_tick_at: dt.datetime | None = None


def last_tick_at() -> dt.datetime | None:
    """When the ticker last completed a pass, or None if it has not yet in this process."""
    return _last_tick_at


def _tick_sync() -> dict[str, str]:
    """One evaluation pass, on a threadpool thread. Owns its own session: the tick runs on
    a timer, unrelated to any request, so there is no request-scoped session to borrow."""
    db = SessionLocal()
    try:
        # Single-user application: the one (oldest) user. When this stops being true, this
        # becomes a loop and nothing else about the design changes.
        user = db.execute(select(User).order_by(User.created_at)).scalars().first()
        if user is None:
            return {}
        return runner.tick(db, user)
    finally:
        db.close()


async def tick_once() -> dict[str, str]:
    """Awaitable tick. Swallows everything — a scheduler that dies on one bad tick is worse
    than one that logs and tries again in five minutes."""
    global _last_tick_at
    try:
        outcomes = await run_in_threadpool(_tick_sync)
        if outcomes:
            log.info("jobs: %s", ", ".join(f"{k}={v}" for k, v in outcomes.items()))
        return outcomes
    except Exception:  # noqa: BLE001 - the ticker must be unkillable
        log.warning("job tick failed; the next tick will retry", exc_info=True)
        return {}
    finally:
        # In `finally`, and deliberately: this records that the TICKER is alive, which is a
        # different claim from "the work succeeded". A tick that raises every time still
        # proves the timer is running; what failed is recorded against the job in
        # `job_runs`. Conflating the two would make a broken job look like a dead scheduler.
        _last_tick_at = dt.datetime.now(dt.UTC)


def start() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    scheduler = AsyncIOScheduler(timezone=settings.app_timezone)
    scheduler.add_job(
        tick_once,
        "interval",
        seconds=settings.job_tick_seconds,
        id="acero-tick",
        # If the process was busy or asleep, run once on return rather than once per
        # missed interval — the tick is idempotent, so a backlog of ticks is pure waste.
        coalesce=True,
        max_instances=1,
        # Generous: a tick that starts late is still useful, and `job_runs` decides what
        # actually executes regardless of when the tick happens to fire.
        misfire_grace_time=600,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("job scheduler started (tick every %ss)", settings.job_tick_seconds)
    return scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    log.info("job scheduler stopped")
