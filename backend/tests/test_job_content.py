"""What the six shipped jobs actually decide.

The property under test throughout: **the job owns the facts, the model owns the voice.**
For the digests that means asserting the model is handed the gathered brief and nothing
else — no tools, no database access, no history. For the nudges it means asserting they say
the right thing once and then stop.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import settings
from app.db.models import GeneratedReview, JournalEntry, Notification, Task
from app.jobs import brief, nudges
from app.services import notifications

TZ = ZoneInfo(settings.app_timezone)


def today() -> dt.date:
    return dt.datetime.now(TZ).date()


def _task(db, user, title, **kw):
    row = Task(user_id=user.id, title=title, status=kw.pop("status", "todo"), **kw)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- the brief is built in SQL --------------------------------------------------------


def test_the_brief_counts_what_actually_happened(db, user):
    now = dt.datetime.now(dt.UTC)
    _task(db, user, "done today", status="done", completed_at=now)
    _task(db, user, "still open")
    _task(db, user, "overdue one", due_at=now - dt.timedelta(hours=3))
    _task(db, user, "due later", due_at=now + dt.timedelta(days=3))

    b = brief._gather(db, user, today())

    assert b["completed_count"] == 1
    assert "done today" in b["completed_titles"]
    assert b["overdue_count"] == 1
    assert b["open_count"] == 3, "todo + in_progress, regardless of due date"
    assert b["journal_written"] is False


def test_the_brief_sees_a_journal_entry(db, user):
    db.add(JournalEntry(user_id=user.id, entry_date=today(), content="wrote something"))
    db.commit()
    assert brief._gather(db, user, today())["journal_written"] is True


def test_deleted_records_are_invisible_to_the_brief(db, user):
    """Soft delete means the row is still there. A summary that counts deleted tasks would
    be reporting things the user believes they removed."""
    t = _task(db, user, "deleted task")
    t.deleted_at = dt.datetime.now(dt.UTC)
    db.commit()
    assert brief._gather(db, user, today())["open_count"] == 0


# --- the model is given the facts and nothing else -------------------------------------


def test_the_prompt_contains_only_the_gathered_facts(db, user, monkeypatch):
    """The property that makes an unreviewed 9pm message safe: the model cannot invent a
    completed task because it was never given the means to look for one."""
    captured: dict = {}

    async def fake_complete(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "You finished one thing today. Two are still waiting."

    from app.core import llm

    monkeypatch.setattr(llm, "complete", fake_complete)

    now = dt.datetime.now(dt.UTC)
    _task(db, user, "shipped the thing", status="done", completed_at=now)
    _task(db, user, "unrelated open task")

    result = brief.day_end_summary(db, user)

    assert result.review is not None
    messages = captured["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    # No tools offered, at all.
    assert "tools" not in captured["kwargs"]
    # The user message is the rendered brief, not the conversation, not the memory.
    facts = messages[1]["content"]
    assert "Tasks completed today: 1" in facts
    # The date is deliberately NOT in the facts: the model parroted it back, and it is
    # the one thing the reader already knows.
    assert "2026-" not in facts
    assert "shipped the thing" in facts
    assert "Tasks still open in total: 1" in facts
    # And the system prompt forbids invention explicitly...
    assert "ONLY the facts" in messages[0]["content"]
    # ...on top of Acero's actual persona. Without it, "in your own voice" means nothing:
    # the first live brief read back the fact list verbatim.
    from app.core.composer import _read_persona

    assert _read_persona()[:60] in messages[0]["content"]


def test_a_digest_is_traced_as_scheduled_work(db, user, monkeypatch):
    """`turns.kind='job'` has been permitted since migration 007 and nothing has ever
    written it. Job spend must land on Insights beside chat, not vanish."""
    from app.core import llm
    from app.db.models import Turn

    async def fake_complete(messages, **kwargs):
        return "A short summary."

    monkeypatch.setattr(llm, "complete", fake_complete)
    _task(db, user, "something open")

    brief.day_end_summary(db, user)

    kinds = db.execute(select(Turn.kind).where(Turn.user_id == user.id)).scalars().all()
    assert "job" in kinds


def test_an_empty_day_says_nothing_rather_than_padding(db, user, monkeypatch):
    """A digest that pads when there is nothing to report trains the reader to ignore it,
    which costs more than the silence would have."""
    from app.core import llm

    called: list[str] = []

    async def fake_complete(messages, **kwargs):
        called.append("called")
        return "..."

    monkeypatch.setattr(llm, "complete", fake_complete)

    result = brief.day_end_summary(db, user)

    assert result.silent is True
    assert result.review is None
    assert called == [], "an empty day must not even cost a model call"


def test_a_model_that_returns_nothing_is_silent_not_broken(db, user, monkeypatch):
    from app.core import llm

    async def fake_complete(messages, **kwargs):
        return "   "

    monkeypatch.setattr(llm, "complete", fake_complete)
    _task(db, user, "something open")

    result = brief.day_end_summary(db, user)
    assert result.silent is True and result.review is None


def test_the_push_body_is_a_pointer_not_the_whole_summary(db, user, monkeypatch):
    from app.core import llm

    long_text = (
        "You closed two things today, which is a good pace. "
        "The report is still open and its deadline has passed. "
        "Nothing was written in the journal."
    )

    async def fake_complete(messages, **kwargs):
        return long_text

    monkeypatch.setattr(llm, "complete", fake_complete)
    _task(db, user, "something open")

    result = brief.day_end_summary(db, user)

    assert result.notify is not None
    assert len(result.notify.body) < len(long_text)
    assert result.notify.body.endswith(".")
    assert result.notify.url == "/#journal/briefings"


def test_a_generated_review_is_never_learned_from(db, user, monkeypatch):
    """Acero must not learn facts from its own output. That is a feedback loop where a
    phrasing hardens into a belief the user never stated."""
    from app.core import llm, memory

    extractions: list = []

    async def fake_complete(messages, **kwargs):
        return "You had a productive day working on the migration."

    async def spy_extract(*args, **kwargs):
        extractions.append(args)

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(memory, "extract_and_store", spy_extract)

    _task(db, user, "something open")
    brief.day_end_summary(db, user)

    assert extractions == [], "the summary must not reach the fact extractor"


# --- nudges ---------------------------------------------------------------------------


def test_overdue_tasks_are_coalesced_into_one_notification(db, user):
    """Three separate pings about three tasks is how people turn notifications off."""
    past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    for i in range(3):
        _task(db, user, f"overdue {i}", due_at=past)

    result = nudges.task_nudge(db, user)

    assert result.notify is not None
    assert result.notify.title == "3 tasks are overdue"
    assert result.detail["overdue"] == 3


def test_one_overdue_task_reads_naturally(db, user):
    _task(db, user, "pay the rent", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    result = nudges.task_nudge(db, user)
    assert result.notify.title == "1 task is overdue"
    assert result.notify.body == "pay the rent"


def test_a_task_still_overdue_is_reminded_against_the_same_record(db, user):
    """⚠ This REPLACES a test asserting the opposite — that the same overdue set is never
    raised twice.

    That rule was written to prevent notification fatigue and produced the opposite failure:
    a task raised once and then silent is a task the system has stopped helping with. The
    reminder now repeats until the user acts, and ends the moment they do.

    It repeats against ONE record rather than writing one per check, so the panel does not
    fill with seven near-identical rows a day and bury everything else.
    """
    _task(db, user, "overdue", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))

    first = nudges.task_nudge(db, user)
    assert first.notify is not None
    row = notifications.raise_notification(db, user, first.notify)

    # The check runs hourly; interruptions are paced separately. Age the delivery past the
    # pacing interval so this asserts the reminder itself, not the pacing.
    row.pushed_at = dt.datetime.now(dt.UTC) - nudges.REMIND_EVERY
    db.commit()

    second = nudges.task_nudge(db, user)

    assert second.silent is False, "an unaddressed overdue task is still worth saying"
    assert second.notify is None, "not a second record"
    assert second.remind is not None and second.remind.record.id == row.id
    assert second.detail["overdue"] == 1


def test_the_check_runs_more_often_than_it_interrupts(db, user):
    """⚠ How fast you FIND OUT and how often you are REMINDED are different numbers.

    They were briefly the same one. Running the job every two hours meant the repetition
    interval had silently become the detection delay too: a task falling due at 11:05 was not
    overdue at the 11:00 check and went unmentioned until 13:03.

    The job now checks hourly and paces the interruptions itself, so a check that finds
    nothing new to say is silent rather than a buzz.
    """
    _task(db, user, "overdue", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5))

    first = nudges.task_nudge(db, user)
    row = notifications.raise_notification(db, user, first.notify)
    row.pushed_at = dt.datetime.now(dt.UTC)
    db.commit()

    held = nudges.task_nudge(db, user)
    assert held.silent is True, "an hourly check must not become an hourly buzz"
    assert held.remind is None
    assert held.detail["holding"] is True

    # ...and once the interval has passed, it does interrupt again.
    row.pushed_at = dt.datetime.now(dt.UTC) - nudges.REMIND_EVERY - dt.timedelta(seconds=1)
    db.commit()
    assert nudges.task_nudge(db, user).remind is not None


def test_a_record_that_never_reached_a_device_is_always_due(db, user):
    """Pacing measures time since the last INTERRUPTION. A record held back by quiet hours
    has interrupted nobody, so there is nothing to pace and the next check tries again."""
    _task(db, user, "overdue", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    first = nudges.task_nudge(db, user)
    row = notifications.raise_notification(db, user, first.notify)
    assert row.pushed_at is None, "no subscription in this test, so it never got out"

    again = nudges.task_nudge(db, user)
    assert again.remind is not None and again.remind.record.id == row.id


def test_renaming_an_overdue_task_updates_what_the_reminder_says(db, user):
    """The reminder describes the situation as it reads NOW.

    Re-sending the record without this would repeat the title the task had when the record
    was first written — for the rest of the day. The tag pins WHICH situation this is; the
    wording is a description of it, not a transcript of something said.
    """
    task = _task(db, user, "buy gifts", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    first = nudges.task_nudge(db, user)
    row = notifications.raise_notification(db, user, first.notify)
    assert row.body == "buy gifts"
    row.pushed_at = dt.datetime.now(dt.UTC) - nudges.REMIND_EVERY
    db.commit()

    task.title = "buy gifts for both sisters"
    db.commit()

    again = nudges.task_nudge(db, user)

    assert again.remind is not None
    assert again.remind.record.id == row.id, "the same record, not a new one"
    assert again.remind.body == "buy gifts for both sisters"
    assert again.remind.record.created_at == row.created_at, "still overdue since the same time"


def test_the_last_check_is_before_the_day_end_summary(db, user):
    """`day_end_summary` fires at 21:00 and already lists what is overdue. Two notifications
    arriving together saying overlapping things is how a reminder starts reading as noise."""
    from app.jobs.registry import get

    nudge_hours = _fire_hours(get("task_nudge"))
    assert max(nudge_hours) == 19
    assert 21 not in nudge_hours
    assert max(nudge_hours) < min(_fire_hours(get("day_end_summary")))


def test_removing_the_reminder_does_not_stop_it(db, user):
    """Deleting a notification is tidying a panel, not answering a task.

    In production the single overdue notification ever raised was deleted, and — combined
    with the unbounded suppression this replaces — that silenced the feature entirely.
    """
    _task(db, user, "overdue", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    first = nudges.task_nudge(db, user)
    row = notifications.raise_notification(db, user, first.notify)
    notifications.delete_notification(db, user.id, row.id)

    second = nudges.task_nudge(db, user)

    assert second.notify is not None, "a fresh record, since the old one is gone"
    assert second.remind is None


def test_a_rescheduled_task_that_goes_overdue_again_is_news(db, user):
    """⚠ THE production regression, end to end. Reconstructed exactly from the live data.

    `task_nudge` raised one notification in the lifetime of the application, on 2026-08-24 at
    19:04:53, for a single overdue task. That notification was never delivered — the browser
    did not subscribe until 20:17:55, 73 minutes later — and was then removed from the panel.
    The task was rescheduled; its new due time passed on 2026-08-26 at 10:00; and every run
    after that returned `{"overdue": 1, "already_told": true}`.

    The cause: the tag hashed task ids alone, so `{gifts}` -> `{}` -> `{gifts}` produced the
    identical tag at both ends. The tag sampled the state and could not represent the
    transition, and the lookback had no time bound, so the second episode was suppressed by
    the first indefinitely.

    Two independent fixes have to hold for this test to pass: the due time is part of the
    fingerprint, so a reschedule is a different situation; and there is no suppression left
    to be silenced by.
    """
    task = _task(db, user, "buy gifts", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2))

    first = nudges.task_nudge(db, user)
    assert first.notify is not None
    row = notifications.raise_notification(db, user, first.notify)
    original_tag = first.notify.tag

    # The user removes it from the panel, exactly as happened in production.
    notifications.delete_notification(db, user.id, row.id)

    # ...and reschedules the task, so it stops being overdue.
    task.due_at = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    db.commit()
    assert nudges.task_nudge(db, user).silent is True

    # The new due time passes.
    task.due_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    db.commit()

    again = nudges.task_nudge(db, user)

    assert again.silent is False, (
        "this returned silent with already_told=True for three days in production"
    )
    assert again.notify is not None
    assert again.notify.tag != original_tag, (
        "the same task at a different due time is a different situation, and the tag has "
        "to be able to say so"
    )


def test_moving_the_due_time_out_stops_the_reminders(db, user):
    """One of the two exits, and the behaviour the repetition exists to train."""
    task = _task(db, user, "overdue", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    assert nudges.task_nudge(db, user).notify is not None

    task.due_at = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    db.commit()

    assert nudges.task_nudge(db, user).silent is True


def test_a_changed_overdue_set_is_news_again(db, user):
    """Idempotence must not become silence. Completing one task changes the situation, and
    the next nudge is genuinely new information."""
    past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    a = _task(db, user, "first", due_at=past)
    _task(db, user, "second", due_at=past)

    first = nudges.task_nudge(db, user)
    notifications.raise_notification(db, user, first.notify)

    a.status, a.completed_at = "done", dt.datetime.now(dt.UTC)
    db.commit()

    second = nudges.task_nudge(db, user)
    assert second.notify is not None
    assert second.notify.title == "1 task is overdue"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda t: setattr(t, "status", "done"), id="completed"),
        pytest.param(lambda t: setattr(t, "status", "dropped"), id="dropped"),
        pytest.param(lambda t: setattr(t, "deleted_at", dt.datetime.now(dt.UTC)), id="deleted"),
        pytest.param(
            lambda t: setattr(t, "snoozed_until", dt.datetime.now(dt.UTC) + dt.timedelta(days=1)),
            id="snoozed",
        ),
    ],
)
def test_finished_and_snoozed_tasks_are_silent(db, user, mutate):
    """Nudging a snoozed task would make the snooze button a lie."""
    t = _task(db, user, "overdue", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    mutate(t)
    db.commit()

    assert nudges.task_nudge(db, user).silent is True


def test_no_overdue_tasks_is_silent_success(db, user):
    _task(db, user, "due next week", due_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=7))
    assert nudges.task_nudge(db, user).silent is True


# --- budget ----------------------------------------------------------------------------


def test_budget_watch_is_silent_without_a_limit(db, user):
    assert user.monthly_budget_usd is None
    assert nudges.budget_watch(db, user).silent is True


def test_budget_watch_warns_once_at_eighty_percent(db, user, monkeypatch):
    from app.services import insights

    user.monthly_budget_usd = Decimal("10.00")
    db.commit()
    monkeypatch.setattr(insights, "spend_since", lambda *a, **k: Decimal("8.50"))

    first = nudges.budget_watch(db, user)
    assert first.notify is not None
    assert "85%" in first.notify.title

    notifications.raise_notification(db, user, first.notify)
    assert nudges.budget_watch(db, user).silent is True, "told once, not every day"


def test_budget_watch_says_something_different_at_the_limit(db, user, monkeypatch):
    from app.services import insights

    user.monthly_budget_usd = Decimal("10.00")
    db.commit()
    monkeypatch.setattr(insights, "spend_since", lambda *a, **k: Decimal("10.50"))

    result = nudges.budget_watch(db, user)
    assert "limit reached" in result.notify.title.lower()
    assert result.detail["reached"] == "limit"


def test_budget_watch_is_silent_below_the_warning_line(db, user, monkeypatch):
    from app.services import insights

    user.monthly_budget_usd = Decimal("10.00")
    db.commit()
    monkeypatch.setattr(insights, "spend_since", lambda *a, **k: Decimal("2.00"))
    assert nudges.budget_watch(db, user).silent is True


# --- journal ----------------------------------------------------------------------------


def test_journal_nudge_is_silent_when_something_was_written(db, user):
    db.add(JournalEntry(user_id=user.id, entry_date=today(), content="wrote"))
    db.commit()
    assert nudges.journal_nudge(db, user).silent is True


def test_journal_nudge_speaks_once_on_an_empty_day(db, user):
    first = nudges.journal_nudge(db, user)
    assert first.notify is not None

    notifications.raise_notification(db, user, first.notify)
    assert nudges.journal_nudge(db, user).silent is True


def test_journal_nudge_ships_switched_off(db, user):
    """A considered product decision, asserted so it cannot be flipped by accident: the
    day-end summary 30 minutes later already reports whether the journal was written."""
    from app.jobs import get

    assert get("journal_nudge").default_on is False


# --- what the digests write --------------------------------------------------------------


def test_a_briefing_is_stored_and_readable_by_date(db, user, monkeypatch):
    from app.core import llm
    from app.jobs import registry, runner

    async def fake_complete(messages, **kwargs):
        return "A short account of the day."

    monkeypatch.setattr(llm, "complete", fake_complete)
    _task(db, user, "something open")

    from .conftest import TEST_PREFIX

    runner.run_job(db, registry.get("day_end_summary"), user, f"{TEST_PREFIX}digest", force=True)

    review = db.execute(
        select(GeneratedReview).where(GeneratedReview.user_id == user.id)
    ).scalar_one()
    assert review.kind == "daily"
    assert review.content == "A short account of the day."
    assert review.period_start.astimezone(TZ).date() == today()

    note = db.execute(select(Notification).where(Notification.user_id == user.id)).scalar_one()
    assert note.kind == "day_end_summary"


# --- disk_watch ----------------------------------------------------------------------------
#
# Disk is the only reading on this box whose exhaustion STOPS the system rather than slowing
# it: Postgres refuses writes, there is no backup, and nothing warns first. So it earns a job
# where memory and load do not.
#
# The design problem is not detecting a full disk. It is not saying so twenty-eight times.


def _disk(monkeypatch, percent: float):
    """Point the job's reader at a synthetic disk. It shares this function with the vitals
    endpoint deliberately — one definition of "how full is the disk", not two that drift."""
    from app.services import vitals

    total = 10_000_000_000
    monkeypatch.setattr(
        vitals,
        "disk",
        lambda *a, **k: vitals.Capacity(used_bytes=int(total * percent / 100), total_bytes=total),
    )


def _run_disk_watch(db, user, key: str) -> str:
    from app.jobs import registry, runner

    from .conftest import TEST_PREFIX

    return runner.run_job(db, registry.get("disk_watch"), user, f"{TEST_PREFIX}{key}", force=True)


def test_disk_watch_is_silent_below_the_threshold(db, user, monkeypatch):
    _disk(monkeypatch, 42)
    assert _run_disk_watch(db, user, "disk-quiet") == "silent"
    assert db.execute(select(Notification).where(Notification.user_id == user.id)).all() == []


def test_disk_watch_speaks_once_on_crossing_the_threshold(db, user, monkeypatch):
    _disk(monkeypatch, 82)
    assert _run_disk_watch(db, user, "disk-cross") == "ok"

    note = db.execute(select(Notification).where(Notification.user_id == user.id)).scalar_one()
    assert note.kind == "disk"
    assert "82%" in note.title
    assert note.tag == "disk-80"


def test_disk_watch_does_not_repeat_itself_within_the_same_band(db, user, monkeypatch):
    """A disk sitting at 81% for a week must not produce twenty-eight notifications. The tag
    is the 5% BAND, not the percentage, so a reading oscillating around a single number
    cannot chatter either."""
    _disk(monkeypatch, 82)
    assert _run_disk_watch(db, user, "disk-1") == "ok"

    _disk(monkeypatch, 84)  # same band
    assert _run_disk_watch(db, user, "disk-2") == "silent"

    rows = db.execute(select(Notification).where(Notification.user_id == user.id)).scalars().all()
    assert len(rows) == 1


def test_disk_watch_speaks_again_when_it_crosses_into_a_worse_band(db, user, monkeypatch):
    """Getting worse is new information, and must not be swallowed by the suppression that
    stops it repeating."""
    _disk(monkeypatch, 82)
    _run_disk_watch(db, user, "disk-a")
    _disk(monkeypatch, 87)
    assert _run_disk_watch(db, user, "disk-b") == "ok"

    tags = {
        n.tag
        for n in db.execute(select(Notification).where(Notification.user_id == user.id))
        .scalars()
        .all()
    }
    assert tags == {"disk-80", "disk-85"}


def test_disk_watch_speaks_again_once_the_window_has_passed(db, user, monkeypatch):
    """An unresolved condition is repeated daily, rather than reported once in the lifetime
    of the installation. This is what the 24-hour window on `already_said` buys."""
    import datetime as dt

    _disk(monkeypatch, 82)
    _run_disk_watch(db, user, "disk-old")
    old = db.execute(select(Notification).where(Notification.user_id == user.id)).scalar_one()
    old.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=30)
    db.commit()

    assert _run_disk_watch(db, user, "disk-new") == "ok"


def test_an_unreadable_disk_is_not_reported_as_a_full_one(db, user, monkeypatch):
    """⚠ The failure that would destroy the value of this notification.

    Reporting exhaustion because a syscall failed teaches the user to ignore the one
    notification that must be believed."""
    from app.services import vitals

    monkeypatch.setattr(vitals, "disk", lambda *a, **k: None)

    assert _run_disk_watch(db, user, "disk-blind") == "silent"
    assert db.execute(select(Notification).where(Notification.user_id == user.id)).all() == []


# --- deleting a briefing ---------------------------------------------------------------


def test_deleting_a_briefing_does_not_cause_it_to_be_written_again(db, user, monkeypatch):
    """A property of the exactly-once design rather than something the delete path handles.

    `job_runs` records what has run; `generated_reviews` is only that job's OUTPUT. Had it
    been the other way round, deleting a briefing would have cost money to replace it.
    """
    from app.core import llm
    from app.jobs import registry, runner
    from app.services import journal as journal_svc

    calls = []

    async def fake_complete(messages, **kwargs):
        calls.append(1)
        return "A short account of the day."

    monkeypatch.setattr(llm, "complete", fake_complete)
    _task(db, user, "something open")

    from .conftest import TEST_PREFIX

    key = f"{TEST_PREFIX}nodup"
    runner.run_job(db, registry.get("day_end_summary"), user, key, force=True)
    briefing = journal_svc.list_briefings(db, user.id)[0]
    assert len(calls) == 1

    journal_svc.delete_briefing(db, user.id, briefing.id)
    assert journal_svc.list_briefings(db, user.id) == []

    # The same occurrence again: the run record is untouched, so nothing re-fires.
    assert runner.run_job(db, registry.get("day_end_summary"), user, key) == "duplicate"
    assert len(calls) == 1, "no model call — and therefore nothing spent"
    assert journal_svc.list_briefings(db, user.id) == [], "and no replacement was written"


def test_a_deleted_briefing_is_restorable_with_the_same_identity(db, user):
    import datetime as dt

    from app.db.models import GeneratedReview
    from app.services import journal as journal_svc

    row = GeneratedReview(
        user_id=user.id,
        kind="daily",
        period_start=dt.datetime.now(dt.UTC),
        period_end=dt.datetime.now(dt.UTC),
        content="An account of a day.",
        delivered_to=[],
    )
    db.add(row)
    db.commit()

    journal_svc.delete_briefing(db, user.id, row.id)
    assert journal_svc.list_briefings(db, user.id) == []

    restored = journal_svc.restore_briefing(db, user.id, row.id)
    assert restored.id == row.id
    assert [b.id for b in journal_svc.list_briefings(db, user.id)] == [row.id]


def _fire_hours(job) -> set[int]:
    """Which local hours a job fires in, sampled from the real trigger rather than parsed."""
    import datetime as _dt
    from zoneinfo import ZoneInfo as _Z

    from app.config import settings as _s

    tz = _Z(_s.app_timezone)
    trigger = job.trigger()
    cursor = _dt.datetime(2026, 6, 1, tzinfo=tz)
    hours = set()
    for _ in range(40):
        nxt = trigger.get_next_fire_time(None, cursor)
        if nxt is None or nxt > cursor + _dt.timedelta(days=2):
            break
        hours.add(nxt.astimezone(tz).hour)
        cursor = nxt + _dt.timedelta(microseconds=1)
    return hours
