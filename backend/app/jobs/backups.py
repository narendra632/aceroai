"""Copying the database off the machine, and proving the copy is good.

Three jobs, because three things fail independently:

- `db_backup` makes a copy. Nightly.
- `restore_check` proves the newest copy restores. Monthly.
- `backup_watch` notices when either has stopped happening. Daily.

**Why `backup_watch` is a separate job and must stay one.** A job that does not run cannot
report that it did not run. Merging the staleness check into `db_backup` would produce a
system that reports its failures only while it is healthy enough to run, which is the exact
shape of backup monitoring that looks fine for a year and then turns out to be decorative.
It is worth resisting the tidy-looking refactor that merges them.

**How failure is reported here.** The runner records an unhandled exception as `failed` and
does not notify — that is the isolation guarantee and it is right, because most jobs failing
is not something to wake someone for. A backup is: an unreported failed backup is
indistinguishable from a backup. So these jobs catch the failures they can name and hand
back a notification, which the runner then records as `ok` — the job did its job, which was
to make a copy *or say why it could not*. `services.backups.last_successful_at` therefore
identifies a real success by the `object` key in `detail`, never by the status.
"""

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.adapters.object_store import ObjectStoreError, configured_store
from app.config import settings
from app.db.models import User
from app.jobs.registry import JobResult, job
from app.jobs.registry import Notification as NotificationSpec
from app.services import backups

log = logging.getLogger(__name__)


@job(
    "db_backup",
    # 02:30, when nothing else runs and nobody is typing. `retention_sweep` is at 03:15, so
    # the copy is taken BEFORE the nightly prune rather than after it — a backup that has
    # already had old traces removed from it is a slightly poorer record for no gain.
    "30 2 * * *",
    description="Copies the whole database to cloud storage, every night.",
    # Six hours: a restart or a transient refusal must not silently cost a whole night,
    # and a copy taken late is worth very nearly as much as one taken on time. Well under
    # the 24-hour gap, so it stays a real window rather than "however late".
    catch_up=dt.timedelta(hours=6),
)
def db_backup(db: Session, user: User) -> JobResult:
    """Take a full copy of the database and store it off the machine."""
    store = configured_store()
    reason = backups.unavailable_reason(store)
    if reason is not None:
        # Not a failure. A developer machine has no bucket and must not fail every night
        # against storage that was never meant to exist. Production's protection against
        # this being how it silently stops is `backup_watch`, which reports the absence of
        # copies without caring why they are absent.
        return JobResult(silent=True, detail={"skipped": reason})

    try:
        detail = backups.write_backup(db, store)
    except (backups.BackupError, ObjectStoreError) as exc:
        log.warning("db_backup could not store a copy: %s", exc)
        return JobResult(
            notify=NotificationSpec(
                kind="backup",
                title="Tonight's backup did not happen",
                body=f"{exc}. The last good copy is still there; this needs looking at.",
                url="/#settings",
                # Dated, so an unresolved problem says so again tomorrow rather than being
                # silenced by the tag of the notification that reported it the first time.
                tag=f"backup-failed-{dt.datetime.now(dt.UTC):%Y-%m-%d}",
            ),
            # Deliberately NO "object" key — see `backups.last_successful_at`.
            detail={"error": type(exc).__name__},
        )

    return JobResult(detail=detail)


@job(
    "restore_check",
    # 04:00 on the 1st. After the month's last nightly copy, and well clear of it.
    "0 4 1 * *",
    description="Rebuilds the newest backup into a scratch database to prove it still works.",
    catch_up=dt.timedelta(hours=12),
)
def restore_check(db: Session, user: User) -> JobResult:
    """Prove the newest copy restores and contains what it said it contained.

    Silent on success. A monthly "your backup is fine" notification is a monthly invitation
    to stop reading notifications, and the one that matters is the other one.
    """
    store = configured_store()
    reason = backups.unavailable_reason(store)
    if reason is not None:
        return JobResult(silent=True, detail={"skipped": reason})

    try:
        detail = backups.verify_newest(store)
    except (backups.BackupError, ObjectStoreError) as exc:
        log.warning("restore_check failed: %s", exc)
        return JobResult(
            notify=NotificationSpec(
                kind="backup",
                title="A backup could not be restored",
                body=f"{exc}. Backups are being written but cannot be relied on.",
                url="/#settings",
                tag=f"restore-failed-{dt.datetime.now(dt.UTC):%Y-%m}",
            ),
            detail={"error": type(exc).__name__},
        )

    return JobResult(detail=detail)


@job(
    "backup_watch",
    # 10:00, deliberately a different hour from the job it watches. If both were driven by
    # the same occurrence, whatever stopped one could stop the other unnoticed.
    "0 10 * * *",
    description="Tells you when backups have stopped happening.",
    catch_up=dt.timedelta(hours=6),
)
def backup_watch(db: Session, user: User) -> JobResult:
    """Report when no copy has succeeded recently — including when none ever has.

    This job never looks at storage and never takes a copy. It asks one question of the run
    history, so that it keeps working in exactly the circumstances where everything else has
    stopped.
    """
    if not settings.backup_bucket:
        # Nothing is configured, so nothing is expected. On a developer machine this is
        # correct; in production it is caught at deploy, not nightly by a notification the
        # user cannot act on from their phone.
        return JobResult(silent=True, detail={"skipped": "no backup bucket configured"})

    stale, hours = backups.staleness(db)
    if not stale:
        return JobResult(silent=True, detail={"hours_since": round(hours or 0, 1)})

    if hours is None:
        title = "The database has never been backed up"
        body = "No backup has ever completed. Everything depends on one disk right now."
    else:
        title = "Backups have stopped"
        body = (
            f"The last good copy was {hours / 24:.1f} days ago. "
            "Nothing since then could be recovered."
        )

    # Dated, following `disk_watch`: an unresolved condition is repeated daily rather than
    # announced once. A backup that stopped a week ago is not less urgent than one that
    # stopped yesterday — it is more.
    tag = f"backup-stale-{dt.datetime.now(dt.UTC):%Y-%m-%d}"
    return JobResult(
        notify=NotificationSpec(kind="backup", title=title, body=body, url="/#settings", tag=tag),
        detail={"hours_since": round(hours, 1) if hours is not None else None},
    )
