"""Whether a job is switched on, and what the user sees about it.

`user_job_prefs` is **sparse**: absence means "use the job's declared default". That single
choice is what makes adding a future job a code change with no migration, no backfill, and
no per-user default row — which was an explicit requirement of this change rather than a
convenient accident.
"""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import JobRun, UserJobPref
from app.jobs.registry import Job, all_jobs, get


def is_enabled(db: Session, user_id: uuid.UUID, job: Job) -> bool:
    stored = db.execute(
        select(UserJobPref.enabled).where(
            UserJobPref.user_id == user_id, UserJobPref.job_name == job.name
        )
    ).scalar_one_or_none()
    return job.default_on if stored is None else stored


def set_enabled(db: Session, user_id: uuid.UUID, job_name: str, enabled: bool) -> None:
    """Upsert one preference. Unknown job names are refused rather than stored — a typo
    that persists silently would be indistinguishable from a job that was removed."""
    if get(job_name) is None:
        raise KeyError(job_name)
    row = db.execute(
        select(UserJobPref).where(UserJobPref.user_id == user_id, UserJobPref.job_name == job_name)
    ).scalar_one_or_none()
    if row is None:
        db.add(UserJobPref(user_id=user_id, job_name=job_name, enabled=enabled))
    else:
        row.enabled = enabled
    db.commit()


def _last_run(db: Session, job_name: str) -> JobRun | None:
    return (
        db.execute(
            select(JobRun).where(JobRun.job_name == job_name).order_by(JobRun.started_at.desc())
        )
        .scalars()
        .first()
    )


def describe(db: Session, user_id: uuid.UUID) -> list[dict]:
    """Every job, as the Settings screen shows it.

    `schedule` is sent as the raw cron expression *and* as a human phrase. The expression
    is the truth; the phrase is what a person reads. Rendering the phrase server-side keeps
    one implementation rather than a second one in TypeScript that can drift.
    """
    out: list[dict] = []
    for job in all_jobs():
        last = _last_run(db, job.name)
        out.append(
            {
                "name": job.name,
                "description": job.description,
                "schedule": job.schedule,
                "when": human_schedule(job.schedule),
                "uses_ai": job.uses_ai,
                "default_on": job.default_on,
                "enabled": is_enabled(db, user_id, job),
                "last_run_at": last.started_at if last else None,
                "last_status": last.status if last else None,
            }
        )
    return out


_DAYS = {
    "sun": "Sunday",
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
}


def human_schedule(expr: str) -> str:
    """A cron expression as a short English phrase.

    Covers only the shapes this application actually uses, and says so by falling back to
    the raw expression rather than guessing. A schedule description that is subtly wrong is
    worse than one that is obviously technical.
    """
    minute, hour, dom, month, dow = expr.split()
    if dom != "*" or month != "*":
        return expr

    def at(h: str) -> str:
        return f"{int(h):02d}:{int(minute):02d}"

    if dow in _DAYS:
        return f"{_DAYS[dow]}s at {at(hour)}" if hour.isdigit() else expr
    if dow != "*":
        return expr
    if hour.isdigit():
        return f"every day at {at(hour)}"
    if "-" in hour:
        # `9-21` or `9-21/2`. The step arrived with the two-hourly overdue nudge; without
        # handling it this fell through to the raw expression, which is honest but is not
        # something to show a person in Settings.
        span, _, step = hour.partition("/")
        start, _, end = span.partition("-")
        if start.isdigit() and end.isdigit() and (step == "" or step.isdigit()):
            window = f"between {int(start):02d}:00 and {int(end):02d}:00"
            if step in ("", "1"):
                return f"hourly {window}"
            return f"every {int(step)} hours {window}"
    if hour.startswith("*/") and hour[2:].isdigit():
        return f"every {int(hour[2:])} hours"
    return expr


def summarise_runs(db: Session, since: dt.datetime) -> dict[str, int]:
    """Counts by status, for the Learn page and for debugging a quiet scheduler."""
    rows = db.execute(select(JobRun.status).where(JobRun.started_at >= since)).scalars().all()
    counts: dict[str, int] = {}
    for status in rows:
        counts[status] = counts.get(status, 0) + 1
    return counts
