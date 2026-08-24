"""Deciding what is due, and running it exactly once.

The scheduler is only a ticker. **This module and the `job_runs` table are the source of
truth** about whether a job has run — which matters because APScheduler's state is in
memory, and a deploy at 20:58 would otherwise kill the 21:00 summary with no error anywhere.

The rule is:

    occurrence = the most recent scheduled instant at or before now
    if job_runs has no row for (job, occurrence):  run it

`UNIQUE (job_name, occurrence_key)` then makes exactly-once a database guarantee rather
than something this code has to be careful about. A repeated tick, a second process and a
manual trigger all converge on one execution.

**The catch-up window is a policy, not a limit.** A job missed by more than its window is
recorded `missed` and NOT run late, because a morning brief delivered at 6pm is noise, not
a late delivery. And only the *most recent* occurrence is ever considered, so a VM that was
off for three days wakes up and sends one summary, not three.
"""

import datetime as dt
import logging
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import GeneratedReview, JobRun, User
from app.jobs.registry import Job, JobResult, all_jobs
from app.services import budget, job_prefs

log = logging.getLogger(__name__)

# Bounds every job's database work. Housekeeping must never WAIT on a lock a real request
# is holding — giving up costs one occurrence, and the next tick retries. Lifted out of
# services/retention.py, where it used to protect only the sweep.
LOCK_TIMEOUT = "3s"
STATEMENT_TIMEOUT = "60s"

# Guards the forward walk in `most_recent_occurrence` against a pathological schedule.
# The realistic worst case is 7 days of an hourly job — 91 steps, measured at 3.3 ms.
_MAX_STEPS = 10_000

# How far back to look when a job has nothing due, purely to answer "was something missed?".
# Distinct from a job's catch-up window: that decides whether to RUN, this decides whether
# to RECORD. Without it a run lost to an outage leaves no trace at all, and "nothing
# happened" is indistinguishable from "nothing was supposed to happen".
_MISS_LOOKBACK = dt.timedelta(days=7)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def now_local() -> dt.datetime:
    return dt.datetime.now(_tz())


def most_recent_occurrence(
    job: Job, now: dt.datetime, lookback: dt.timedelta | None = None
) -> dt.datetime | None:
    """The last scheduled instant at or before `now`, no earlier than `now - lookback`.

    APScheduler's `CronTrigger` only walks forward, so rather than add a dependency for a
    backwards walk this steps forward from the start of the window and keeps the last fire
    time that has not passed `now`.

    `lookback` defaults to the job's catch-up window, in which case a `None` result means
    "nothing is due". Passing the longer `_MISS_LOOKBACK` answers the different question
    "what was the last thing that *should* have happened", which is how a missed run gets
    recorded rather than silently forgotten.
    """
    trigger = job.trigger()
    if lookback is None:
        # `catch_up=None` means "however late" — bounded only by how far back it is worth
        # looking at all, so such a job is never recorded missed.
        lookback = job.catch_up if job.catch_up is not None else _MISS_LOOKBACK
    cursor = now - lookback
    found: dt.datetime | None = None
    for _ in range(_MAX_STEPS):
        nxt = trigger.get_next_fire_time(None, cursor)
        if nxt is None or nxt > now:
            break
        found = nxt
        # `get_next_fire_time` is inclusive of `now`, so step past the instant we just took
        # or the walk would not advance.
        cursor = nxt + dt.timedelta(microseconds=1)
    return found


def occurrence_key(when: dt.datetime) -> str:
    """The stored form of an occurrence. Stable and exact — two spellings of the same
    instant must never produce two rows."""
    return when.isoformat()


def already_ran(db: Session, job_name: str, key: str) -> bool:
    """Whether this occurrence has a terminal record. A `missed` row counts: it is a
    decision that was made, and remaking it every tick would fill the table."""
    return (
        db.execute(
            select(JobRun.id).where(JobRun.job_name == job_name, JobRun.occurrence_key == key)
        ).first()
        is not None
    )


def has_ever_run(db: Session, job_name: str) -> bool:
    """Whether this job has any recorded history at all."""
    return (
        db.execute(select(JobRun.id).where(JobRun.job_name == job_name).limit(1)).first()
        is not None
    )


def _record(
    db: Session,
    job_name: str,
    key: str,
    status: str,
    *,
    started: dt.datetime | None = None,
    error_type: str | None = None,
    detail: dict | None = None,
) -> None:
    """Write the outcome. Uniquely constrained, so a race records once and the loser is
    swallowed — which is exactly the intended behaviour, not an error to report."""
    row = JobRun(
        id=uuid.uuid4(),
        job_name=job_name,
        occurrence_key=key,
        status=status,
        finished_at=dt.datetime.now(dt.UTC),
        error_type=error_type,
        detail=detail,
    )
    if started is not None:
        row.duration_ms = round((dt.datetime.now(dt.UTC) - started).total_seconds() * 1000)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        log.debug("job_runs row for %s@%s already existed; nothing to do", job_name, key)


def _apply_timeouts(db: Session) -> None:
    db.execute(text(f"SET lock_timeout = '{LOCK_TIMEOUT}'"))
    db.execute(text(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'"))
    db.commit()


def _reset_timeouts(db: Session) -> None:
    # A pooled connection would otherwise carry these into whatever runs next.
    try:
        db.execute(text("RESET lock_timeout"))
        db.execute(text("RESET statement_timeout"))
        db.commit()
    except Exception:  # noqa: BLE001 - a dead connection has nothing to reset
        db.rollback()


def _lock_key(job_name: str) -> str:
    return f"acero:job:{job_name}"


def run_job(db: Session, job: Job, user: User, key: str, *, force: bool = False) -> str:
    """Run one job for one occurrence. Returns the recorded status.

    Catches everything and re-raises nothing: a failing job must not be able to stop the
    scheduler, affect another job, or reach the code serving the user. Its failure is
    recorded and that is the whole of its blast radius.
    """
    if not force and already_ran(db, job.name, key):
        return "duplicate"

    if not force and not job_prefs.is_enabled(db, user.id, job):
        _record(db, job.name, key, "skipped_disabled")
        return "skipped_disabled"

    # Redundant with the unique constraint above, and kept on purpose: it is what keeps
    # this correct if a second worker, a second container, or a hand-run `python -m
    # app.jobs.run` ever executes concurrently with the scheduler.
    locked = db.execute(
        text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": _lock_key(job.name)}
    ).scalar()
    if not locked:
        log.info("job %s is already running elsewhere; skipping this tick", job.name)
        return "locked"

    started = dt.datetime.now(dt.UTC)
    try:
        if job.uses_ai:
            try:
                budget.check(db, user)
            except Exception as exc:  # noqa: BLE001 - any refusal means do not spend
                log.info("job %s skipped: %s", job.name, type(exc).__name__)
                _record(db, job.name, key, "skipped_budget", started=started)
                return "skipped_budget"

        _apply_timeouts(db)
        result = job.run(db, user)
        _deliver(db, user, job, result)
        status = "silent" if result.silent else "ok"
        _record(db, job.name, key, status, started=started, detail=result.detail)
        return status
    except Exception as exc:  # noqa: BLE001 - the isolation guarantee itself
        log.warning("job %s failed; nothing else is affected", job.name, exc_info=True)
        db.rollback()
        _record(db, job.name, key, "failed", started=started, error_type=type(exc).__name__)
        return "failed"
    finally:
        _reset_timeouts(db)
        try:
            db.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": _lock_key(job.name)})
            db.commit()
        except Exception:  # noqa: BLE001 - the lock dies with the connection anyway
            db.rollback()


def _deliver(db: Session, user: User, job: Job, result: JobResult) -> None:
    """Persist what the job produced. Imported here rather than at module scope so the
    runner does not pull the notification stack into every import of this module."""
    from app.services import notifications

    if result.review is not None:
        db.add(
            GeneratedReview(
                user_id=user.id,
                kind=result.review.kind,
                period_start=result.review.period_start,
                period_end=result.review.period_end,
                content=result.review.content,
                delivered_to=[],
            )
        )
        db.commit()

    if result.notify is not None:
        notifications.raise_notification(db, user, result.notify, job_name=job.name)


def tick(db: Session, user: User, now: dt.datetime | None = None) -> dict[str, str]:
    """Evaluate every job and run whatever is due. Returns {job_name: status}.

    A pure function of `now` and the database — no scheduler, no event loop, no sleeping —
    which is what makes the whole system testable by calling this with a chosen `now`.
    """
    now = now or now_local()
    outcomes: dict[str, str] = {}
    for entry in all_jobs():
        try:
            status = _evaluate(db, entry, user, now)
            if status is not None:
                outcomes[entry.name] = status
        except Exception:  # noqa: BLE001 - one job must never stop the others
            log.warning("job %s could not be evaluated", entry.name, exc_info=True)
            outcomes[entry.name] = "failed"
    return outcomes


def _evaluate(db: Session, entry: Job, user: User, now: dt.datetime) -> str | None:
    """Decide this job's fate for this tick. None means "nothing to do, quietly"."""
    due = most_recent_occurrence(entry, now)
    if due is not None:
        key = occurrence_key(due)
        if already_ran(db, entry.name, key):
            return None
        return run_job(db, entry, user, key)

    # A job that never expires cannot be missed; if it had an occurrence, the branch above
    # would have taken it.
    if entry.catch_up is None:
        return None

    # Nothing inside the catch-up window. Either the job genuinely is not due, or an
    # occurrence was lost to an outage — and those must not look the same afterwards.
    stale = most_recent_occurrence(entry, now, _MISS_LOOKBACK)
    if stale is None:
        return None
    key = occurrence_key(stale)
    if already_ran(db, entry.name, key):
        return None

    # A job that has never run cannot have MISSED anything — it did not exist yet. Without
    # this, deploying the feature writes a "missed" row for every job whose last scheduled
    # moment happens to be behind us, which reads as six failures on a healthy first boot.
    # "Missed" means "it used to happen and this time it did not".
    if not has_ever_run(db, entry.name):
        log.info("job %s has no history yet; not treating %s as missed", entry.name, key)
        return None
    log.info("job %s missed its %s run by more than %s", entry.name, key, entry.catch_up)
    _record(db, entry.name, key, "missed")
    return "missed"
