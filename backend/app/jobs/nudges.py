"""Jobs that notice things, without a model.

"Which tasks are overdue" is a query, not a question for a language model. These three jobs
cost nothing, run instantly, and are structurally incapable of inventing a task — which is
why most jobs should look like this and only the two digests do not.

The hard part here is not finding the overdue tasks. It is deciding **when to say it again**,
and the three jobs answer that differently on purpose:

- `budget_watch` reports a measurement crossing into a worse band. Once you know spend passed
  80%, saying it again adds nothing until it passes 100%, so it carries a definition of
  "already said" and stays quiet. Tagged by month, so it speaks once in August and again in
  September.
- `journal_nudge` asks about one day. Tagged by date; once is the whole of it.
- `task_nudge` reports **work you still have to do**. It checks hourly so a task that has
  just fallen due is picked up quickly, and interrupts at most every two hours until you deal
  with it or move the due time out. Those are two different numbers on purpose — see
  `REMIND_EVERY`.

That last one was told-once and it was wrong. A single notification — raised before any
device had subscribed, so never delivered, and then removed from the panel — silenced the
feature for three days with no error anywhere. A reminder you can end in one tap is not
fatigue; a reminder that gives up after one unheard attempt is not a reminder. The behaviour
this trains is "deal with it or reschedule it honestly", and it is deliberately not explained
in the notification text: a reminder that re-explains itself every two hours is a worse one.
"""

import datetime as dt
import hashlib
import logging
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JournalEntry, Task, User
from app.jobs.registry import JobResult, Reminder, job
from app.jobs.registry import Notification as NotificationSpec
from app.services import budget, insights, notifications

log = logging.getLogger(__name__)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


# --- overdue tasks ------------------------------------------------------------------


#: How long to leave between interrupting the user about the same unchanged situation.
#:
#: ⚠ Deliberately NOT the same thing as the schedule, and they were briefly conflated. When
#: the job itself ran every two hours, the repetition interval had silently become the
#: DETECTION delay too: a task falling due at 11:05 was not overdue at the 11:00 check and
#: went unmentioned until 13:03, nearly two hours later.
#:
#: They are two different questions. The schedule answers "how soon do I find out?", this
#: answers "how often am I nagged?". Hourly checks paced to a two-hourly reminder gives a
#: sub-hour answer to the first without changing the second.
REMIND_EVERY = dt.timedelta(hours=2)


@job(
    "task_nudge",
    # Hourly, 09:00 to 19:00. Interruptions are paced by REMIND_EVERY, not by this, so
    # checking often costs one indexed query and buys a fast first nudge.
    #
    # It stops at 19:00 rather than 21:00 because `day_end_summary` fires at 21:00 and
    # already lists what is overdue. Two notifications arriving together saying overlapping
    # things is how a reminder starts reading as noise.
    "0 9-19 * * *",
    description="Reminds you every couple of hours about a task whose due time has passed.",
    # Under the one-hour gap between occurrences: a window at least as long as the gap can
    # never expire, so "missed" would become unreachable — the registry enforces this. In
    # practice the five-minute tick means this runs within minutes of the hour; the bound
    # only matters after an outage, where the next check beats a stale one.
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

    # The tag identifies the SITUATION: which tasks are overdue, and when each was due.
    #
    # ⚠ The due time is in here for a reason found the expensive way. The tag used to hash
    # ids alone, which meant a task that went overdue, was rescheduled, and went overdue again
    # produced the identical tag — so the second episode was suppressed by the notification
    # from the first, permanently. Including `due_at` makes a reschedule what it actually is:
    # a different situation.
    fingerprint = hashlib.sha256(
        ",".join(f"{t.id}@{t.due_at.isoformat()}" for t in overdue).encode()
    ).hexdigest()[:16]
    tag = f"overdue-{fingerprint}"

    # Composed BEFORE deciding whether this is new or a repeat, because a repeat carries the
    # wording too — renaming an overdue task must not leave the reminder repeating the name
    # it had this morning.
    title, body = _describe(overdue)

    # An overdue task is reported until it is DEALT WITH, not until it has been mentioned
    # once. There is no `already_said` check here, and that asymmetry with `budget_watch` and
    # `disk_watch` is the point: those report a measurement crossing into a worse band, where
    # repeating adds nothing, while this reports work the user still has to do.
    #
    # The repetition ends when the task is completed, dropped, deleted, snoozed, or its due
    # time is moved out — all of which drop it from the query above. Nothing else stops it,
    # including reading or removing the notification.
    existing = notifications.todays_record(db, user.id, "task_overdue", tag)
    if existing is not None:
        if not notifications.reminder_is_due(existing, REMIND_EVERY):
            # Found on an hourly check, but it is not yet time to interrupt again. The job
            # ran and correctly said nothing, which is what `silent` is for.
            return JobResult(silent=True, detail={"overdue": len(overdue), "holding": True})
        return JobResult(
            remind=Reminder(record=existing, title=title, body=body),
            detail={"overdue": len(overdue), "reminder": (existing.push_count or 0) + 1},
        )

    return JobResult(
        notify=NotificationSpec(
            kind="task_overdue", title=title, body=body, url="/#tasks", tag=tag
        ),
        detail={"overdue": len(overdue)},
    )


def _describe(overdue: list[Task]) -> tuple[str, str]:
    """How a set of overdue tasks reads. Recomputed on every reminder, never cached."""
    if len(overdue) == 1:
        return "1 task is overdue", overdue[0].title
    # Coalesced deliberately: one notification naming a couple of them, never one per task.
    # Three separate pings about three tasks is how people turn notifications off.
    body = "; ".join(t.title for t in overdue[:3])
    if len(overdue) > 3:
        body += f" and {len(overdue) - 3} more"
    return f"{len(overdue)} tasks are overdue", body


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
    if notifications.already_said(db, user.id, "budget", tag):
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
    if notifications.already_said(db, user.id, "journal_empty", tag):
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
