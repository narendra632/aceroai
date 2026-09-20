"""Recurring work: what runs on a schedule, and what it is allowed to do.

Importing this package **registers every job**. Anything that needs the registry populated —
the scheduler, the API, the `python -m app.jobs.run` command, the tests — imports this
module, not the individual job files.

    registry.py      what a job IS, and the @job decorator that declares one
    runner.py        what is DUE, and running it exactly once
    scheduler.py     the ticker (APScheduler holds exactly one job: tick)
    run.py           `python -m app.jobs.run` — trigger a job by hand

    housekeeping.py  retention_sweep, disk_watch
    brief.py         morning_brief, day_end_summary   (the only jobs that call a model)
    nudges.py        task_nudge, budget_watch, journal_nudge
    backups.py       db_backup, restore_check, backup_watch

Adding a job is one decorator in one file, plus an import here. Everything else — run
recording, idempotence, failure isolation, the spending check, tracing, the Settings toggle,
quiet hours and the push cap — comes from the registry and cannot be forgotten.
"""

from app.jobs import (  # noqa: F401  (registers the jobs)
    backups,
    brief,
    evening,
    housekeeping,
    nudges,
    prices,
    reading,
)
from app.jobs.registry import (
    Job,
    JobResult,
    Notification,
    ReviewDraft,
    all_jobs,
    get,
    job,
)

__all__ = [
    "Job",
    "JobResult",
    "Notification",
    "ReviewDraft",
    "all_jobs",
    "get",
    "job",
]
