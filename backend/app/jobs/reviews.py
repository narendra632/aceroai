"""Looking backwards, on a schedule.

Three jobs, and the cadence is the design.

**Saturday morning** no market is open and nothing is urgent, which is exactly why the weekly
review happens then. It is the artefact actually worth reading — the daily notifications are
operational, this is where the thinking accumulates.

**The first of the month** adds the questions a week is too short to answer: which sources
produced anything, and whether the confidence levels have been honest.

**Each quarter** asks the hardest one, against the criteria committed to in advance.

⚠ **Sunday is deliberately empty.** There is a real risk in a system like this that it fills
every available slot with output, and output is not insight. Nothing runs on Sunday and that
is a decision, not an omission.

⚠ **None of these calls a model.** A review is almost entirely numbers, and everywhere else in
this module a model is forbidden from producing one. A paragraph summarising the figures would
be the single place in the design where a number could be restated wrongly with nothing to
check it against — so the facts are assembled by code and the page renders them.
"""

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models import User
from app.jobs.registry import JobResult, job
from app.jobs.registry import Notification as NotificationSpec
from app.services.investments import reviews


def _deliver(db: Session, user: User, kind: str, *, url: str) -> JobResult:
    row = reviews.write(db, user, kind)
    db.commit()

    if row is None:
        # ⚠ Not a failure. A catch-up run reaching the same period twice must leave the first
        # review alone: two copies of one review will eventually disagree, and neither would
        # be wrong on its face.
        return JobResult(silent=True, detail={"reason": f"this {kind.lower()} already has one"})

    return JobResult(
        detail={
            "kind": kind,
            "period": f"{row.period_start} to {row.period_end}",
            "decisions": sum(row.content["decisions"]["counts"].values()),
            "queue_waiting": row.content["queue"]["waiting"],
        },
        notify=NotificationSpec(
            kind=f"investments_{kind.lower()}_review",
            title=f"Your {kind.lower()} review is ready",
            body=row.headline,
            url=url,
            tag=f"{kind.lower()}-review-{row.period_end.isoformat()}",
        ),
    )


@job(
    "investments_weekly_review",
    # Saturday 09:00. No market is open, nothing is urgent, and the week is complete.
    "0 9 * * sat",
    description="Saturday morning: what happened this week, and what is waiting on you.",
    catch_up=dt.timedelta(hours=12),
)
def investments_weekly_review(db: Session, user: User) -> JobResult:
    """The week's decisions, refusals, near-misses, queue and budget.

    ⚠ It leads with what needs doing rather than with the week's return. A review whose first
    line is a number invites reading only that number, and this early the numbers are the part
    that means least.
    """
    return _deliver(db, user, "WEEKLY", url="/#investments")


@job(
    "investments_monthly_review",
    # The 1st, after the weekly has had its Saturday.
    "30 9 1 * *",
    description="Month end: plus which sources produced anything, and whether it was calibrated.",
    catch_up=dt.timedelta(hours=12),
)
def investments_monthly_review(db: Session, user: User) -> JobResult:
    """The week, plus the questions a week is too short to answer.

    ⚠ Source attribution appears here and not weekly. Over seven days it is noise wearing a
    number, and showing it weekly would train its reader to read noise.
    """
    return _deliver(db, user, "MONTHLY", url="/#investments")


@job(
    "investments_quarterly_review",
    # 1 Jan, Apr, Jul, Oct — an hour after the monthly, so both exist and neither races.
    "30 10 1 jan,apr,jul,oct *",
    description="Quarter end: the long look, against the criteria committed to in advance.",
    catch_up=dt.timedelta(hours=12),
)
def investments_quarterly_review(db: Session, user: User) -> JobResult:
    """The deepest look, and the one that eventually answers whether this was worth doing."""
    return _deliver(db, user, "QUARTERLY", url="/#investments")
