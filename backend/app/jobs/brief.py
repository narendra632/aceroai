"""The two jobs where a model writes, and the one rule that makes that safe.

    The job owns the facts. The model owns the voice.

`_gather` builds a brief entirely in SQL — tasks done, tasks open, tasks overdue, whether a
journal entry exists, what the day cost. `_compose` hands the model **that dictionary and
nothing else**, with an instruction to phrase it.

The model has no database access, no tools, and no ability to look anything up. It therefore
cannot invent a completed task, because it was never given the means to look for one — it
was handed a number. That property is what makes a message written at 21:00 and read before
you are properly awake safe to send unreviewed.

The alternative — letting a job call `handle_message` with tools available — was considered
and rejected. An agent taking actions unsupervised at 3am is a different risk class from an
agent answering a question you just asked.

One further rule, enforced in `runner._deliver` and asserted by a test: a generated review is
**never** fed to the memory extractor. Learning facts from your own output is a feedback loop
where a phrasing hardens into a belief.
"""

import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JournalEntry, Task, User
from app.jobs.registry import JobResult, Notification, ReviewDraft, job
from app.services import user_settings

log = logging.getLogger(__name__)

# The model is asked for prose and nothing else. Short because the notification body is
# derived from it and a push payload is a pointer, not an essay.
MAX_WORDS = 90

# The instruction wrapped around the persona. Two jobs: bound the length, and forbid
# invention — the model is handed counts, not a search, so anything it adds is fabricated.
_INSTRUCTION = (
    "You are writing a short personal note to the user, in your own voice.\n\n"
    "Use ONLY the facts listed in the message. Do not invent anything, do not add advice "
    "the facts do not support, and do not use headings, bullets or markdown.\n"
    "Do not restate the numbers mechanically or repeat today's date back to them - they "
    "know what day it is. Say what actually matters, and say less when there is less to "
    "say.\n"
    f"At most {MAX_WORDS} words, in 2-4 short sentences. Speak to them directly."
)


def _system_prompt() -> str:
    """Acero's persona, then the instruction.

    ⚠ The persona was MISSING in the first version of this, and it showed immediately. The
    first live morning brief read: *"Today is August 24, 2026, and you have zero tasks due
    today and zero overdue tasks. You still have one open task in total."* — accurate, and
    a robotic recitation of the fact list.

    "In your own voice" is meaningless without the file that defines the voice. This reuses
    `composer._read_persona` rather than re-reading SOUL.md, so a job and a chat reply speak
    as the same assistant and there is one loader (and one prod `SOUL_PATH` override) to
    keep working.
    """
    from app.core.composer import _read_persona

    return f"{_read_persona()}\n\n---\n\n{_INSTRUCTION}"


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def _day_bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(day, dt.time.min, tzinfo=_tz())
    return start, start + dt.timedelta(days=1)


def _gather(db: Session, user: User, day: dt.date) -> dict:
    """Everything the summary may mention, established in SQL.

    Deliberately plain counts and short title lists. Anything the model might want that is
    not here simply cannot appear in the output, which is the point.
    """
    start, end = _day_bounds(day)

    completed = list(
        db.execute(
            select(Task.title).where(
                Task.user_id == user.id,
                Task.deleted_at.is_(None),
                Task.completed_at.is_not(None),
                Task.completed_at >= start,
                Task.completed_at < end,
            )
        )
        .scalars()
        .all()
    )

    open_tasks = (
        db.execute(
            select(Task)
            .where(
                Task.user_id == user.id,
                Task.deleted_at.is_(None),
                Task.status.in_(("todo", "in_progress")),
            )
            .order_by(Task.due_at.is_(None), Task.due_at, Task.priority)
        )
        .scalars()
        .all()
    )

    now = dt.datetime.now(dt.UTC)
    overdue = [t for t in open_tasks if t.due_at is not None and t.due_at < now]
    due_today = [t for t in open_tasks if t.due_at is not None and start <= t.due_at < end]

    journalled = (
        db.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(
                JournalEntry.user_id == user.id,
                JournalEntry.deleted_at.is_(None),
                JournalEntry.entry_date == day,
            )
        ).scalar_one()
        or 0
    ) > 0

    return {
        "date": day.isoformat(),
        "completed_count": len(completed),
        "completed_titles": completed[:5],
        "open_count": len(open_tasks),
        "overdue_count": len(overdue),
        "overdue_titles": [t.title for t in overdue[:5]],
        "due_today_count": len(due_today),
        "due_today_titles": [t.title for t in due_today[:5]],
        "journal_written": journalled,
    }


def _has_substance(brief: dict) -> bool:
    """Whether there is anything worth saying. A digest that pads when the day was empty
    trains the reader to ignore it, which costs more than the silence would have."""
    return bool(
        brief["completed_count"]
        or brief["open_count"]
        or brief["overdue_count"]
        or brief["due_today_count"]
        or brief["journal_written"]
    )


def _render_facts(brief: dict, *, forward_looking: bool) -> str:
    """The brief as plain lines for the prompt. Written out rather than dumped as JSON so
    the model reads facts rather than a data structure."""
    lines: list[str] = []
    if forward_looking:
        lines.append(f"Tasks due today: {brief['due_today_count']}")
        if brief["due_today_titles"]:
            lines.append("  " + "; ".join(brief["due_today_titles"]))
    else:
        lines.append(f"Tasks completed today: {brief['completed_count']}")
        if brief["completed_titles"]:
            lines.append("  " + "; ".join(brief["completed_titles"]))
    lines.append(f"Tasks overdue: {brief['overdue_count']}")
    if brief["overdue_titles"]:
        lines.append("  " + "; ".join(brief["overdue_titles"]))
    lines.append(f"Tasks still open in total: {brief['open_count']}")
    lines.append("Journal entry written today: " + ("yes" if brief["journal_written"] else "no"))
    return "\n".join(lines)


async def _compose(user: User, facts: str) -> str:
    """One model call. No tools, no memory recall, no history — only the facts above.

    Non-streaming: nobody is watching this arrive, so there is no first-token latency worth
    optimising, and `complete` is the simpler path.

    Traced as `turns.kind="job"`, so what the summaries cost appears on Insights as its own
    slice beside chat, embeddings and extraction. That enum value has been permitted since
    migration 007 and this is the first thing to write it.
    """
    from app.core import llm, telemetry

    provider, model = user_settings.resolve(user)
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": facts},
    ]
    tl = telemetry.Timeline()
    usage: dict = {}
    ok, error_type = True, None
    try:
        with tl.stage("compose"):
            text = await llm.complete(messages, provider=provider, model=model, usage=usage)
        return (text or "").strip()
    except Exception as exc:  # noqa: BLE001 - recorded, then handled by the caller
        ok, error_type = False, type(exc).__name__
        log.warning("digest composition failed", exc_info=True)
        return ""
    finally:
        await telemetry.record(
            tl,
            user.id,
            "job",
            channel="job",
            provider=provider,
            model=model,
            usage=usage,
            ok=ok,
            error_type=error_type,
        )


def _first_sentence(text: str, limit: int = 120) -> str:
    """The push body: one line pointing at the full text, never the whole thing."""
    flat = " ".join(text.split())
    for stop in (". ", "! ", "? "):
        head = flat.split(stop)[0]
        if head != flat and len(head) <= limit:
            return head + stop.strip()
    return flat[:limit].rstrip() + ("…" if len(flat) > limit else "")


def _run_digest(db: Session, user: User, *, kind: str, day: dt.date, title: str) -> JobResult:
    brief = _gather(db, user, day)
    if not _has_substance(brief):
        return JobResult(detail={"reason": "nothing to report"}, silent=True)

    facts = _render_facts(brief, forward_looking=kind == "morning")
    # Jobs are sync and run on a threadpool thread with no event loop of its own, so
    # `asyncio.run` is correct here rather than a borrowed loop. The one async thing a job
    # does is the model call; making the whole job machinery async to accommodate it would
    # trade a well-understood line for a pervasive complication.
    text = asyncio.run(_compose(user, facts))
    if not text:
        return JobResult(detail={"reason": "model returned nothing"}, silent=True)

    start, end = _day_bounds(day)
    return JobResult(
        review=ReviewDraft(kind=kind, content=text, period_start=start, period_end=end),
        notify=Notification(
            kind="morning_brief" if kind == "morning" else "day_end_summary",
            title=title,
            body=_first_sentence(text),
            url="/#journal/briefings",
            tag=f"{kind}-{day.isoformat()}",
        ),
        detail={k: v for k, v in brief.items() if not k.endswith("_titles")},
    )


@job(
    "morning_brief",
    "30 7 * * *",
    uses_ai=True,
    description="What today looks like — due tasks, anything overdue, where you left off.",
    # Delivered by 11:30 or not at all. A "morning brief" arriving in the afternoon is not
    # a late morning brief, it is a wrong one.
    catch_up=dt.timedelta(hours=4),
)
def morning_brief(db: Session, user: User) -> JobResult:
    today = dt.datetime.now(_tz()).date()
    return _run_digest(db, user, kind="morning", day=today, title="Your morning brief")


@job(
    "day_end_summary",
    "0 21 * * *",
    uses_ai=True,
    description="A short look back at your day, at 9pm.",
    # By midnight, so it still lands on the day it describes.
    catch_up=dt.timedelta(hours=3),
)
def day_end_summary(db: Session, user: User) -> JobResult:
    today = dt.datetime.now(_tz()).date()
    return _run_digest(db, user, kind="daily", day=today, title="Your day, in short")
