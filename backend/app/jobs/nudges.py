"""Jobs that notice things, without a model.

"Which tasks are overdue" is a query, not a question for a language model. These three jobs
cost nothing, run instantly, and are structurally incapable of inventing a task — which is
why most jobs should look like this and only the two digests do not.

The hard part here is not finding the overdue tasks. It is **not telling you twice.** A
nudge that repeats every hour is worse than no nudge at all: you stop reading them, and then
the one that mattered goes unread too. So each job carries its own definition of "already
said", and `task_nudge` re-raises only when the set of overdue tasks has actually changed.
"""

import datetime as dt
import hashlib
import logging
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JournalEntry, Notification, Task, User
from app.jobs.registry import JobResult, job
from app.jobs.registry import Notification as NotificationSpec
from app.services import budget, insights

log = logging.getLogger(__name__)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def _already_said(db: Session, user_id, kind: str, tag: str) -> bool:
    """Whether this exact thing has already been raised.

    The `tag` carries the state being reported — for overdue tasks, a hash of which tasks
    they are. Same tag means the situation has not changed, so saying it again would be
    repetition rather than news.
    """
    return (
        db.execute(
            select(Notification.id)
            .where(
                Notification.user_id == user_id,
                Notification.kind == kind,
                Notification.tag == tag,
            )
            .limit(1)
        ).first()
        is not None
    )


# --- overdue tasks ------------------------------------------------------------------


@job(
    "task_nudge",
    "0 9-21 * * *",
    description="A quiet nudge when a task's due time has passed.",
    # Under an hour, because the occurrences are an hour apart — a longer window could
    # never expire, and "missed" would become unreachable. In practice the five-minute tick
    # means this runs within minutes; the bound only matters after an outage, where the
    # next hour's nudge is a better answer than a stale one.
    catch_up=dt.timedelta(minutes=45),
)
def task_nudge(db: Session, user: User) -> JobResult:
    now = dt.datetime.now(dt.UTC)
    overdue = (
        db.execute(
            select(Task)
            .where(
                Task.user_id == user.id,
                Task.deleted_at.is_(None),
                Task.status.in_(("todo", "in_progress")),
                Task.due_at.is_not(None),
                Task.due_at < now,
                # A snoozed task has been explicitly deferred by the user. Nudging anyway
                # would make the snooze button a lie.
                (Task.snoozed_until.is_(None)) | (Task.snoozed_until <= now),
            )
            .order_by(Task.due_at)
        )
        .scalars()
        .all()
    )
    if not overdue:
        return JobResult(silent=True)

    # The tag IS the state: which tasks are overdue right now. If nothing has changed since
    # the last nudge, the tag matches and we stay quiet. Complete one and the tag changes,
    # so the next nudge is genuinely new information.
    fingerprint = hashlib.sha256(",".join(str(t.id) for t in overdue).encode()).hexdigest()[:16]
    tag = f"overdue-{fingerprint}"
    if _already_said(db, user.id, "task_overdue", tag):
        return JobResult(silent=True, detail={"overdue": len(overdue), "already_told": True})

    if len(overdue) == 1:
        title = "1 task is overdue"
        body = overdue[0].title
    else:
        title = f"{len(overdue)} tasks are overdue"
        # Coalesced deliberately: one notification naming a couple of them, never one per
        # task. Three separate pings about three tasks is how people turn notifications off.
        body = "; ".join(t.title for t in overdue[:3])
        if len(overdue) > 3:
            body += f" and {len(overdue) - 3} more"

    return JobResult(
        notify=NotificationSpec(
            kind="task_overdue", title=title, body=body, url="/#tasks", tag=tag
        ),
        detail={"overdue": len(overdue)},
    )


# --- spend ---------------------------------------------------------------------------


@job(
    "budget_watch",
    "0 9 * * *",
    description="Tells you when this month's spend passes 80% of your limit.",
    # Generous: a spend warning is just as useful in the evening as at nine in the morning.
    catch_up=dt.timedelta(hours=12),
)
def budget_watch(db: Session, user: User) -> JobResult:
    limit = user.monthly_budget_usd
    if limit is None or limit <= 0:
        return JobResult(silent=True, detail={"reason": "no limit set"})

    spent = insights.spend_since(db, user.id, budget.month_start())
    ratio = float(spent / limit) if limit else 0.0
    if ratio < budget.WARN_RATIO:
        return JobResult(silent=True, detail={"ratio": round(ratio, 3)})

    reached = "limit" if ratio >= 1.0 else "warn"
    # Scoped to the month, so crossing 80% tells you once in August and again in September.
    tag = f"budget-{reached}-{dt.datetime.now(_tz()):%Y-%m}"
    if _already_said(db, user.id, "budget", tag):
        return JobResult(silent=True, detail={"ratio": round(ratio, 3), "already_told": True})

    if reached == "limit":
        title = "Monthly spend limit reached"
        body = f"${spent:.2f} of ${Decimal(limit):.2f}. Replies are paused until next month."
    else:
        title = f"{ratio:.0%} of your monthly limit used"
        body = f"${spent:.2f} of ${Decimal(limit):.2f} so far this month."

    return JobResult(
        notify=NotificationSpec(kind="budget", title=title, body=body, url="/#settings", tag=tag),
        detail={"ratio": round(ratio, 3), "reached": reached},
    )


# --- journal --------------------------------------------------------------------------


@job(
    "journal_nudge",
    "30 20 * * *",
    description="A reminder to write in your journal if the day has none.",
    # By 22:30. A prompt to write about today, delivered tomorrow, is just noise.
    catch_up=dt.timedelta(hours=2),
    # OFF by default, and that is a considered product decision rather than caution.
    #
    # The day-end summary at 21:00 already says whether you journalled, so this is a second
    # interruption 30 minutes earlier carrying the same information. Notification fatigue is
    # the most common way a feature like this dies — you stop reading them, and then the one
    # that mattered goes unread too. Built because it was asked for, off because three
    # scheduled pings a day is the ceiling worth designing to. One switch away in Settings.
    default_on=False,
)
def journal_nudge(db: Session, user: User) -> JobResult:
    today = dt.datetime.now(_tz()).date()
    written = (
        db.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(
                JournalEntry.user_id == user.id,
                JournalEntry.deleted_at.is_(None),
                JournalEntry.entry_date == today,
            )
        ).scalar_one()
        or 0
    )
    if written:
        return JobResult(silent=True, detail={"entries": written})

    tag = f"journal-{today.isoformat()}"
    if _already_said(db, user.id, "journal_empty", tag):
        return JobResult(silent=True, detail={"already_told": True})

    return JobResult(
        notify=NotificationSpec(
            kind="journal_empty",
            title="Nothing written today",
            body="A line or two is enough.",
            url="/#journal",
            tag=tag,
        )
    )
