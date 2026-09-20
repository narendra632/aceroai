"""Jobs nobody sees.

`retention_sweep` is deliberately the first job this project has, because it has no model
call, no notification and no interface — so it exercises the scheduling machinery and
nothing else.

It also fixes a real defect rather than adding a feature. Retention used to run off the back
of a delivered reply, gated by an in-memory flag, which meant three things:

  - a week without messaging Acero was a week with nothing pruned,
  - it took DELETE locks on `turns`/`spans` while the app was in use, so its 3-second
    `lock_timeout` usually made it give up rather than do the work,
  - the state was memory-only, so every deploy re-armed it.

03:15 fixes all three. It is also the only job with `catch_up=None` — "however late" —
because sweeping late is strictly better than not sweeping at all. That is the opposite of a
morning brief, where late delivery is worse than silence, and it is exactly why that value
has to be stated out loud rather than reached by choosing a large number.
"""

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.jobs.registry import JobResult, job
from app.jobs.registry import Notification as NotificationSpec
from app.services import notifications, retention, vitals

log = logging.getLogger(__name__)


@job(
    "retention_sweep",
    "15 3 * * *",
    description="Rolls yesterday's costs into permanent totals and prunes old traces.",
    # However late. Housekeeping deferred is housekeeping that still needs doing.
    catch_up=None,
)
def retention_sweep(db: Session, user: User) -> JobResult:
    counts = retention.sweep(db)
    counts["notifications_pruned"] = retention.prune_notifications(db)
    # Silent when there was nothing to prune, which is the common case on a quiet week and
    # must not read as a failure in `job_runs`.
    did_something = any(counts.values())
    return JobResult(detail=counts, silent=not did_something)


@job(
    "disk_watch",
    "0 */6 * * *",
    description="Warns when the disk is filling up, before Postgres stops accepting writes.",
    # Under the 6-hour gap, or the registry refuses it at import — a window that cannot
    # expire is a window that says "always deliver" while looking like a staleness policy.
    catch_up=dt.timedelta(hours=2),
)
def disk_watch(db: Session, user: User) -> JobResult:
    """Say something before the disk fills, and then stop saying it.

    Disk is the only reading on this box whose exhaustion *stops* the system rather than
    slowing it: Postgres refuses writes, there is no backup, and nothing warns first. Memory
    pressure and load both degrade visibly and recover on their own, which is why they are
    shown on Insights and not watched here — alerting on everything measurable is how a
    notification channel becomes noise.

    **The tag is the band, not the percentage.** A disk sitting at 80.4% would otherwise
    cross and re-cross a single number and report itself every six hours forever. Bands mean
    crossing 80% says so once, 81-84% stays quiet, and crossing 85% is genuinely new.

    The 24-hour window on `already_said` is what makes this a warning rather than a one-time
    announcement. Without it, the first crossing would be the only one ever reported: clear
    some space, drift back up a month later, and a year-old row would silence it. With it,
    an unresolved condition is repeated daily — which is the correct amount of nagging for
    something that needs attention this week rather than this minute.
    """
    reading = vitals.disk()
    if reading is None:
        # ⚠ An unmeasurable disk is NOT a full one. Reporting exhaustion because a syscall
        # failed would train the user to ignore the one notification that must be believed.
        return JobResult(silent=True, detail={"reason": "disk unreadable"})

    percent = reading.percent
    if percent < settings.disk_warn_percent:
        return JobResult(silent=True, detail={"percent": round(percent, 1)})

    band = int(percent // settings.disk_band_percent) * settings.disk_band_percent
    tag = f"disk-{band}"
    if notifications.already_said(db, user.id, "disk", tag, since=dt.timedelta(hours=24)):
        return JobResult(
            silent=True, detail={"percent": round(percent, 1), "band": band, "already_told": True}
        )

    free_gb = (reading.total_bytes - reading.used_bytes) / 1_000_000_000
    return JobResult(
        notify=NotificationSpec(
            kind="disk",
            title=f"Disk is {percent:.0f}% full",
            body=f"{free_gb:.1f} GB left. Postgres stops accepting writes when it runs out.",
            url="/#insights",
            tag=tag,
        ),
        detail={"percent": round(percent, 1), "band": band},
    )


#: The Investments module's share of a disk that is already three-quarters full. Its build
#: spec reserves 250 MB and asks to be warned at 200 MB, and the gap between the two is what
#: makes the warning useful: there is a month of ordinary growth in which to act.
#:
#: ⚠ Module constants rather than settings, deliberately. These are a *design* budget written
#: down in one place, not a preference anyone tunes from the interface — and a number that can
#: be edited away is a number that gets edited away the first time it fires.
INVESTMENTS_BUDGET_BYTES = 250 * 1024 * 1024
INVESTMENTS_WARN_BYTES = 200 * 1024 * 1024


@job(
    "investments_disk_watch",
    # Weekly. The module's projected growth is around 50 MB a year, so a daily check would be
    # eleven identical readings a week apart from the one that matters.
    "0 9 * * mon",
    description="Watches how much disk the investment record is using against its budget.",
    catch_up=dt.timedelta(hours=12),
)
def investments_disk_watch(db: Session, user: User) -> JobResult:
    """Report the Investments module's footprint before it becomes the disk's problem.

    The whole-disk `disk_watch` above answers "is the machine about to stop"; this answers
    "which part of it is growing, and was that the plan". They are different questions, and a
    disk alert that arrives without the second one leaves nothing to act on but guesswork.

    The module's own price record is the part that grows without anyone deciding it should:
    every holding gains an observation every trading day, forever, and nothing in the daily
    path is a reminder that this has a ceiling.
    """
    used = vitals.table_bytes(db, vitals.INVESTMENT_TABLES)
    if used is None:
        # ⚠ An unmeasurable table is NOT an empty one, and is certainly not a full one.
        return JobResult(silent=True, detail={"reason": "table sizes unreadable"})

    megabytes = round(used / 1024 / 1024, 1)
    detail = {"used_mb": megabytes, "budget_mb": INVESTMENTS_BUDGET_BYTES // 1024 // 1024}
    if used < INVESTMENTS_WARN_BYTES:
        return JobResult(silent=True, detail=detail)

    # Banded like `disk_watch`, and repeated daily while unresolved, for the same reasons.
    band = int(used / 1024 / 1024 // 25) * 25
    tag = f"investments-disk-{band}"
    if notifications.already_said(db, user.id, "disk", tag, since=dt.timedelta(hours=24)):
        return JobResult(silent=True, detail={**detail, "already_told": True})

    return JobResult(
        notify=NotificationSpec(
            kind="disk",
            title=f"The investment record is using {megabytes:.0f} MB",
            body=(
                f"Its budget is {INVESTMENTS_BUDGET_BYTES // 1024 // 1024} MB. Daily prices "
                "are what grow — thinning the oldest of them is the lever."
            ),
            url="/#insights",
            tag=tag,
        ),
        detail={**detail, "band": band},
    )
