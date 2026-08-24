"""What a job is, and how one is declared.

Adding a unit of recurring work is a decorator and nothing else:

    @job("day_end_summary", "0 21 * * *", uses_ai=True,
         description="A short look back at your day, at 9pm.")
    def day_end_summary(db: Session, user: User) -> JobResult:
        ...

Everything a job needs and could otherwise forget comes from here rather than from the job:
run recording, idempotence, failure isolation, the spending check, `turns.kind="job"`
tracing, the toggle in Settings, quiet hours and the daily push cap. A job author writes
only the part that is actually specific to their job.

That is a deliberate requirement of this change, not a convenience. A registry where each
job re-implements its own bookkeeping produces jobs that are *almost* correct, and the
failure mode of an almost-correct scheduled job is a summary that silently never arrives.
"""

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from apscheduler.triggers.cron import CronTrigger

from app.config import settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from app.db.models import User


@dataclass(frozen=True)
class Notification:
    """What a job wants the user told. Turned into a row first, a push second."""

    kind: str
    title: str
    body: str
    url: str | None = None
    # Notifications sharing a tag REPLACE one another on the device rather than stacking,
    # so a second overdue-task nudge supersedes the first instead of adding to a pile.
    tag: str | None = None


@dataclass(frozen=True)
class ReviewDraft:
    """A `generated_reviews` row: longer than a notification, kept and readable by date."""

    kind: str  # 'morning' | 'daily' | 'weekly'
    content: str
    period_start: dt.datetime
    period_end: dt.datetime


@dataclass(frozen=True)
class JobResult:
    """What a job hands back.

    `silent` is load-bearing and easy to mistake for a detail. `task_nudge` runs twelve
    times a day and usually finds nothing — that is the job working, not a no-op. Recording
    it distinctly is what keeps `job_runs` readable at a glance: a column of `silent` is
    healthy, a column of `failed` is not, and an absence of rows is a third thing entirely.
    """

    notify: Notification | None = None
    review: ReviewDraft | None = None
    # Counts and identifiers only — this lands in `job_runs.detail`, never message text.
    detail: dict | None = None
    silent: bool = False


JobFn = Callable[["Session", "User"], JobResult]


@dataclass(frozen=True)
class Job:
    name: str
    schedule: str
    run: JobFn
    description: str
    #: Whether this job calls a language model. Drives the budget check and tracing.
    uses_ai: bool = False
    #: Applied when the user has expressed no preference (`user_job_prefs` is sparse).
    default_on: bool = True
    #: How late a missed occurrence may still run, or None for "however late".
    #:
    #: ⚠ This MUST be shorter than the gap between occurrences, and the validation below
    #: enforces it. Measured: a daily job with a 24-hour window can never be missed —
    #: its occurrences are 24 hours apart, so one is always inside the window — which
    #: means a 07:30 brief would still be delivered at 07:29 the NEXT morning. The window
    #: read like a staleness policy while being, in fact, "always deliver".
    #:
    #: `None` says "however late" out loud, for work like retention where sweeping late is
    #: strictly better than not sweeping.
    catch_up: dt.timedelta | None = field(default=dt.timedelta(hours=4))

    def trigger(self) -> CronTrigger:
        from zoneinfo import ZoneInfo

        return CronTrigger.from_crontab(self.schedule, timezone=ZoneInfo(settings.app_timezone))

    def min_period(self) -> dt.timedelta:
        """The shortest gap between two of this job's occurrences.

        Sampled forward from a fixed reference rather than reasoned about, because a cron
        expression's period is not a single number — `0 9-21 * * *` is one hour twelve
        times and then twelve hours overnight, and it is the SHORTEST gap that bounds a
        sensible catch-up window.
        """
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(settings.app_timezone)
        trigger = self.trigger()
        cursor = dt.datetime(2026, 1, 1, tzinfo=tz)
        gap: dt.timedelta | None = None
        previous: dt.datetime | None = None
        for _ in range(60):
            nxt = trigger.get_next_fire_time(None, cursor)
            if nxt is None:
                break
            if previous is not None:
                gap = nxt - previous if gap is None else min(gap, nxt - previous)
            previous = nxt
            cursor = nxt + dt.timedelta(microseconds=1)
        return gap or dt.timedelta(days=1)


_REGISTRY: dict[str, Job] = {}

# A numeric day-of-week is REJECTED, and this is not pedantry — it is a measured trap.
#
# APScheduler numbers days 0=Monday. Standard crontab numbers them 0=Sunday. So
# `0 18 * * 0`, which every crontab reference in the world says is Sunday evening, fires on
# MONDAY here. Verified against this exact APScheduler version: `0 18 * * 0` -> Monday,
# `0 18 * * sun` -> Sunday, `0 18 * * 6` -> Sunday.
#
# Nothing reports an error; the job simply runs on the wrong day forever. Requiring a name
# turns a silent off-by-one into a startup failure.
_NUMERIC_DOW = re.compile(r"^[\d*/,\-]+$")


def _validate(job: Job) -> None:
    if job.name in _REGISTRY:
        raise RuntimeError(f"duplicate job name {job.name!r}")
    if not job.description.strip():
        raise RuntimeError(f"job {job.name!r} has no description — the user has to read it")

    fields = job.schedule.split()
    if len(fields) != 5:
        raise RuntimeError(f"job {job.name!r}: expected 5 cron fields, got {len(fields)}")
    dow = fields[4]
    if dow != "*" and _NUMERIC_DOW.match(dow):
        raise RuntimeError(
            f"job {job.name!r}: day-of-week must be named (sun/mon/...), not {dow!r}. "
            "APScheduler numbers days 0=Monday while crontab uses 0=Sunday, so a numeric "
            "field silently runs on the wrong day."
        )
    try:
        job.trigger()
    except Exception as exc:  # noqa: BLE001 - re-raised with the job named
        raise RuntimeError(f"job {job.name!r}: unparseable schedule {job.schedule!r}") from exc

    # A window at least as long as the gap between occurrences is not a window at all —
    # there is always an occurrence inside it, so the job runs however late it is. That is
    # a legitimate policy for housekeeping and a bug for anything time-sensitive, so it
    # must be spelled `catch_up=None` rather than arrived at by arithmetic.
    if job.catch_up is not None:
        period = job.min_period()
        if job.catch_up >= period:
            raise RuntimeError(
                f"job {job.name!r}: catch_up of {job.catch_up} is not shorter than the "
                f"{period} gap between its occurrences, so it can never be missed and "
                "would be delivered arbitrarily late. Shorten it, or pass catch_up=None "
                "to say 'however late' deliberately."
            )
        if job.catch_up <= dt.timedelta(0):
            raise RuntimeError(f"job {job.name!r}: catch_up must be positive")


def job(
    name: str,
    schedule: str,
    *,
    description: str,
    uses_ai: bool = False,
    default_on: bool = True,
    catch_up: dt.timedelta | None = dt.timedelta(hours=4),
) -> Callable[[JobFn], JobFn]:
    """Register a scheduled job. Validation happens at import, so a malformed job stops
    the application from starting rather than failing silently at its scheduled time.

    Raises rather than asserts, deliberately: `python -O` strips assertions, and this
    guarantee must survive that. Same reason the tool registry raises."""

    def decorate(fn: JobFn) -> JobFn:
        entry = Job(
            name=name,
            schedule=schedule,
            run=fn,
            description=description,
            uses_ai=uses_ai,
            default_on=default_on,
            catch_up=catch_up,
        )
        _validate(entry)
        _REGISTRY[name] = entry
        return fn

    return decorate


def all_jobs() -> list[Job]:
    """Every registered job, in declaration order."""
    return list(_REGISTRY.values())


def get(name: str) -> Job | None:
    return _REGISTRY.get(name)
