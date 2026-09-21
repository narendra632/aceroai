"""The scheduling machinery: what is due, what already ran, and what must never happen.

Every test here calls `tick` or `run_job` directly with a chosen `now`. No scheduler is
started, no event loop is involved, and nothing sleeps — which is the whole reason
APScheduler holds exactly one job and the decisions live in `runner.py`.

Tests use the `jobs_registry` fixture to take the registry over. Running the REAL jobs here
would fire the digests against a live model and write briefings into the developer's own
database.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import settings
from app.db.models import JobRun, Notification
from app.jobs import runner
from app.jobs.registry import JobResult, Reminder
from app.jobs.registry import Notification as NotificationSpec

from .conftest import TEST_PREFIX

TZ = ZoneInfo(settings.app_timezone)


def at(y, m, d, hh, mm=0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=TZ)


def _runs(db, name: str) -> list[JobRun]:
    return list(
        db.execute(select(JobRun).where(JobRun.job_name == name).order_by(JobRun.started_at))
        .scalars()
        .all()
    )


@pytest.fixture
def counting_job(jobs_registry):
    """A job that records how many times it actually executed."""
    calls: list[str] = []

    @jobs_registry.job(
        f"{TEST_PREFIX}counter",
        "0 21 * * *",
        description="A test job.",
        catch_up=dt.timedelta(hours=3),
    )
    def _counter(db, user):
        calls.append("ran")
        return JobResult(detail={"calls": len(calls)})

    return jobs_registry.get(f"{TEST_PREFIX}counter"), calls


# --- declaration is validated at import ---------------------------------------------


def test_a_duplicate_job_name_is_refused(jobs_registry):
    @jobs_registry.job("dupe", "0 1 * * *", description="first")
    def _a(db, user):
        return JobResult()

    with pytest.raises(RuntimeError, match="duplicate job name"):

        @jobs_registry.job("dupe", "0 2 * * *", description="second")
        def _b(db, user):
            return JobResult()


def test_a_job_without_a_description_is_refused(jobs_registry):
    with pytest.raises(RuntimeError, match="no description"):

        @jobs_registry.job("silent", "0 1 * * *", description="   ")
        def _a(db, user):
            return JobResult()


def test_an_unparseable_schedule_is_refused(jobs_registry):
    with pytest.raises(RuntimeError, match="expected 5 cron fields"):

        @jobs_registry.job("short", "0 1 * *", description="too few fields")
        def _a(db, user):
            return JobResult()


def test_a_numeric_day_of_week_is_refused(jobs_registry):
    """MEASURED, not theoretical: APScheduler numbers days 0=Monday while every crontab
    reference uses 0=Sunday, so `0 18 * * 0` fires on MONDAY here. Nothing errors — the job
    simply runs on the wrong day forever. Requiring a name turns that into a startup
    failure."""
    with pytest.raises(RuntimeError, match="day-of-week must be named"):

        @jobs_registry.job("sunday", "0 18 * * 0", description="meant to be Sunday")
        def _a(db, user):
            return JobResult()


def test_a_named_day_of_week_lands_on_that_day(jobs_registry):
    @jobs_registry.job("sunday", "0 18 * * sun", description="Sunday evening")
    def _a(db, user):
        return JobResult()

    entry = jobs_registry.get("sunday")
    # 2026-08-31 is a Monday; the most recent Sunday occurrence is the 30th.
    found = runner.most_recent_occurrence(entry, at(2026, 8, 31, 9), dt.timedelta(days=7))
    assert found is not None
    assert found.strftime("%A") == "Sunday"
    assert found.date() == dt.date(2026, 8, 30)


# --- resolving the due occurrence ----------------------------------------------------


@pytest.mark.parametrize(
    ("schedule", "now", "lookback_hours", "expected"),
    [
        ("0 21 * * *", at(2026, 8, 24, 21, 30), 24, at(2026, 8, 24, 21)),
        ("0 21 * * *", at(2026, 8, 24, 20, 59), 24, at(2026, 8, 23, 21)),
        # `get_next_fire_time` is inclusive, so a tick landing exactly on the hour counts.
        ("0 21 * * *", at(2026, 8, 24, 21, 0), 24, at(2026, 8, 24, 21)),
        # across local midnight
        ("0 21 * * *", at(2026, 8, 25, 0, 30), 24, at(2026, 8, 24, 21)),
        ("0 9-21 * * *", at(2026, 8, 24, 14, 5), 2, at(2026, 8, 24, 14)),
        # before the daily window opens, nothing is due within the lookback
        ("0 9-21 * * *", at(2026, 8, 24, 8, 5), 2, None),
        # a lookback that ends before the occurrence finds nothing
        ("0 21 * * *", at(2026, 8, 25, 1, 30), 3, None),
    ],
)
def test_most_recent_occurrence(jobs_registry, schedule, now, lookback_hours, expected):
    """The lookback is passed explicitly here so the ALGORITHM is tested independently of
    the catch-up policy that normally supplies it — the two are separate concerns and a
    change to the policy must not silently rewrite what this asserts."""

    @jobs_registry.job("probe", schedule, description="probe", catch_up=dt.timedelta(minutes=30))
    def _a(db, user):
        return JobResult()

    found = runner.most_recent_occurrence(
        jobs_registry.get("probe"), now, dt.timedelta(hours=lookback_hours)
    )
    assert found == expected


# --- exactly once --------------------------------------------------------------------


def test_the_same_occurrence_runs_only_once(db, user, counting_job):
    entry, calls = counting_job
    key = runner.occurrence_key(at(2026, 8, 24, 21))

    assert runner.run_job(db, entry, user, key) == "ok"
    assert runner.run_job(db, entry, user, key) == "duplicate"
    assert runner.run_job(db, entry, user, key) == "duplicate"

    assert calls == ["ran"], "the work must execute exactly once"
    assert len(_runs(db, entry.name)) == 1


def test_a_repeated_tick_does_not_repeat_the_work(db, user, counting_job):
    entry, calls = counting_job
    now = at(2026, 8, 24, 21, 30)

    assert runner.tick(db, user, now)[entry.name] == "ok"
    assert entry.name not in runner.tick(db, user, now)
    assert entry.name not in runner.tick(db, user, now + dt.timedelta(minutes=5))
    assert calls == ["ran"]


def test_a_later_occurrence_does_run(db, user, counting_job):
    """Idempotence must not become paralysis: tomorrow's 21:00 is a different occurrence."""
    entry, calls = counting_job
    runner.tick(db, user, at(2026, 8, 24, 21, 30))
    runner.tick(db, user, at(2026, 8, 25, 21, 30))
    assert calls == ["ran", "ran"]


# --- catching up, and refusing to ----------------------------------------------------


def test_a_short_outage_is_recovered(db, user, counting_job):
    """The scenario this whole design exists for: a deploy at 20:58 kills the 21:00 run of
    an in-memory scheduler with no error anywhere. Here the next tick picks it up."""
    entry, calls = counting_job
    # 21:00 occurrence, back at 23:45 — inside the three-hour window.
    outcomes = runner.tick(db, user, at(2026, 8, 24, 23, 45))
    assert outcomes[entry.name] == "ok"
    assert calls == ["ran"]


def test_a_long_outage_records_missed_and_does_not_deliver_late(db, user, counting_job):
    """A morning brief delivered at 6pm is noise, not a late delivery. The bound is a
    staleness policy, and a run outside it must still leave a trace.

    The job is given history first, deliberately: a job that has NEVER run cannot have
    missed anything, and is skipped silently instead (see the first-boot test below)."""
    entry, calls = counting_job
    assert runner.tick(db, user, at(2026, 8, 24, 21, 30))[entry.name] == "ok"
    calls.clear()

    # The next day's 21:00 occurrence, reached at 01:30 — four and a half hours late.
    outcomes = runner.tick(db, user, at(2026, 8, 26, 1, 30))

    assert outcomes[entry.name] == "missed"
    assert calls == [], "the job must NOT run late"
    assert [r.status for r in _runs(db, entry.name)] == ["ok", "missed"]


def test_missed_is_recorded_once_not_every_tick(db, user, counting_job):
    entry, _ = counting_job
    runner.tick(db, user, at(2026, 8, 24, 21, 30))  # history, so a gap is meaningful

    late = at(2026, 8, 26, 1, 30)
    runner.tick(db, user, late)
    runner.tick(db, user, late + dt.timedelta(minutes=5))
    runner.tick(db, user, late + dt.timedelta(minutes=10))

    assert [r.status for r in _runs(db, entry.name)] == ["ok", "missed"]


def test_a_catch_up_window_that_can_never_expire_is_refused(jobs_registry):
    """MEASURED: a daily job with a 24-hour window can never be missed, because its
    occurrences are 24 hours apart and one is therefore always inside the window. The
    window reads like a staleness policy while actually meaning "deliver however late" — a
    07:30 brief would still go out at 07:29 the next morning.

    This was the original default. It is now a startup failure."""
    with pytest.raises(RuntimeError, match="never be missed"):

        @jobs_registry.job(
            "always", "0 7 * * *", description="daily", catch_up=dt.timedelta(hours=24)
        )
        def _a(db, user):
            return JobResult()


def test_however_late_must_be_said_out_loud(db, user, jobs_registry):
    """The legitimate version of the same policy. Housekeeping deferred is housekeeping
    that still needs doing — but it is spelled `None`, not reached by arithmetic."""
    calls: list[str] = []

    @jobs_registry.job(f"{TEST_PREFIX}forever", "0 3 * * *", description="whenever", catch_up=None)
    def _forever(db_, user_):
        calls.append("ran")
        return JobResult()

    entry = jobs_registry.get(f"{TEST_PREFIX}forever")
    # Twenty hours late and still delivered, with no "missed" record.
    outcomes = runner.tick(db, user, at(2026, 8, 24, 23, 0))
    assert outcomes[entry.name] == "ok"
    assert calls == ["ran"]


def test_every_shipped_job_has_a_window_that_can_actually_expire():
    """Runs against the REAL registry. The validation above fires at import, so this is
    belt-and-braces — but it also documents which job deliberately opts out."""
    from app.jobs import all_jobs

    forever = [j.name for j in all_jobs() if j.catch_up is None]
    assert forever == ["retention_sweep"], (
        "only housekeeping should run however late; anything the user READS must expire"
    )
    for entry in all_jobs():
        if entry.catch_up is not None:
            assert entry.catch_up < entry.min_period(), entry.name


def test_missed_occurrences_do_not_accumulate(db, user, jobs_registry):
    """A machine off for three days must wake up and send ONE summary, not three."""
    calls: list[str] = []

    @jobs_registry.job(f"{TEST_PREFIX}daily", "0 21 * * *", description="daily")
    def _daily(db_, user_):
        calls.append("ran")
        return JobResult()

    entry = jobs_registry.get(f"{TEST_PREFIX}daily")
    # Back after three days, half an hour past the most recent occurrence.
    runner.tick(db, user, at(2026, 8, 27, 21, 30))
    assert calls == ["ran"]
    assert len(_runs(db, entry.name)) == 1


# --- isolation -----------------------------------------------------------------------


def test_a_failing_job_is_recorded_and_contained(db, user, jobs_registry):
    order: list[str] = []

    @jobs_registry.job(f"{TEST_PREFIX}boom", "0 21 * * *", description="explodes")
    def _boom(db_, user_):
        order.append("boom")
        raise ValueError("deliberate")

    @jobs_registry.job(f"{TEST_PREFIX}after", "0 21 * * *", description="runs anyway")
    def _after(db_, user_):
        order.append("after")
        return JobResult()

    # tick itself must not raise
    outcomes = runner.tick(db, user, at(2026, 8, 24, 21, 30))

    assert outcomes[f"{TEST_PREFIX}boom"] == "failed"
    assert outcomes[f"{TEST_PREFIX}after"] == "ok", "one job must not stop another"
    assert order == ["boom", "after"]

    row = _runs(db, f"{TEST_PREFIX}boom")[0]
    assert row.status == "failed"
    assert row.error_type == "ValueError"


def test_nothing_to_report_is_success_not_failure(db, user, jobs_registry):
    """`task_nudge` runs seven times a day and usually finds nothing. That is the job
    working, and it must be readable at a glance as distinct from a failure — and from a
    run that never happened at all."""

    @jobs_registry.job(f"{TEST_PREFIX}quiet", "0 21 * * *", description="usually quiet")
    def _quiet(db_, user_):
        return JobResult(silent=True, detail={"found": 0})

    status = runner.run_job(db, jobs_registry.get(f"{TEST_PREFIX}quiet"), user, f"{TEST_PREFIX}k1")
    assert status == "silent"
    assert _runs(db, f"{TEST_PREFIX}quiet")[0].status == "silent"


# --- policy --------------------------------------------------------------------------


def test_a_disabled_job_does_not_run_and_says_so(db, user, jobs_registry):
    calls: list[str] = []

    @jobs_registry.job(f"{TEST_PREFIX}off", "0 21 * * *", description="off", default_on=False)
    def _off(db_, user_):
        calls.append("ran")
        return JobResult()

    status = runner.run_job(db, jobs_registry.get(f"{TEST_PREFIX}off"), user, f"{TEST_PREFIX}k2")
    assert status == "skipped_disabled"
    assert calls == []
    assert _runs(db, f"{TEST_PREFIX}off")[0].status == "skipped_disabled"


def test_a_user_preference_overrides_the_declared_default(db, user, jobs_registry):
    """`user_job_prefs` is sparse — absence means the default. This is what makes adding a
    future job need no migration."""
    from app.services import job_prefs

    @jobs_registry.job(f"{TEST_PREFIX}off", "0 21 * * *", description="off", default_on=False)
    def _off(db_, user_):
        return JobResult()

    entry = jobs_registry.get(f"{TEST_PREFIX}off")
    assert job_prefs.is_enabled(db, user.id, entry) is False

    job_prefs.set_enabled(db, user.id, entry.name, True)
    assert job_prefs.is_enabled(db, user.id, entry) is True


def test_an_unknown_job_preference_is_refused(db, user, jobs_registry):
    """A preference for a job that does not exist is indistinguishable afterwards from a
    job that was removed, and would sit in the table forever looking meaningful."""
    from app.services import job_prefs

    with pytest.raises(KeyError):
        job_prefs.set_enabled(db, user.id, "no-such-job", True)


def test_the_spending_limit_stops_a_model_using_job(db, user, jobs_registry, monkeypatch):

    from app.services import budget

    calls: list[str] = []

    @jobs_registry.job(f"{TEST_PREFIX}ai", "0 21 * * *", description="uses ai", uses_ai=True)
    def _ai(db_, user_):
        calls.append("ran")
        return JobResult()

    @jobs_registry.job(f"{TEST_PREFIX}free", "0 21 * * *", description="no ai")
    def _free(db_, user_):
        calls.append("free")
        return JobResult()

    def _over(_db, _user):
        raise budget.BudgetExceeded("over")

    monkeypatch.setattr(budget, "check", _over)

    outcomes = runner.tick(db, user, at(2026, 8, 24, 21, 30))

    assert outcomes[f"{TEST_PREFIX}ai"] == "skipped_budget"
    assert outcomes[f"{TEST_PREFIX}free"] == "ok", "a spend limit must not stop free work"
    assert calls == ["free"]


# --- what a job produces --------------------------------------------------------------


def test_a_notification_is_written_even_when_push_is_unconfigured(db, user, jobs_registry):
    """The rule the whole notification design rests on: write the row, then attempt
    delivery. CI has no VAPID keys, which is exactly the "cannot deliver" case."""

    @jobs_registry.job(f"{TEST_PREFIX}notify", "0 21 * * *", description="notifies")
    def _notify(db_, user_):
        return JobResult(
            notify=NotificationSpec(
                kind="test", title="Something happened", body="Details inside.", url="/#tasks"
            )
        )

    runner.run_job(db, jobs_registry.get(f"{TEST_PREFIX}notify"), user, f"{TEST_PREFIX}k3")

    rows = db.execute(select(Notification).where(Notification.user_id == user.id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "Something happened"
    assert rows[0].pushed_at is None, "never delivered, but certainly recorded"


def test_a_job_writing_a_review_stores_it(db, user, jobs_registry):
    from app.db.models import GeneratedReview
    from app.jobs.registry import ReviewDraft

    start = at(2026, 8, 24, 0)

    @jobs_registry.job(f"{TEST_PREFIX}review", "0 21 * * *", description="writes a review")
    def _review(db_, user_):
        return JobResult(
            review=ReviewDraft(
                kind="daily",
                content="A quiet day.",
                period_start=start,
                period_end=start + dt.timedelta(days=1),
            )
        )

    runner.run_job(db, jobs_registry.get(f"{TEST_PREFIX}review"), user, f"{TEST_PREFIX}k4")

    rows = (
        db.execute(select(GeneratedReview).where(GeneratedReview.user_id == user.id))
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].content == "A quiet day."


# --- the real registry ----------------------------------------------------------------


def test_every_registered_job_is_well_formed():
    """Runs against the REAL registry, without the fixture, so the shipped jobs are
    checked rather than only the synthetic ones above."""
    from app.jobs import all_jobs

    jobs = all_jobs()
    assert jobs, "the application ships with no jobs at all"
    names = [j.name for j in jobs]
    assert len(names) == len(set(names))
    for entry in jobs:
        assert entry.description.strip()
        assert entry.trigger() is not None
        assert entry.catch_up is None or entry.catch_up > dt.timedelta(0)


def test_almost_nothing_calls_a_model():
    """Most work should be SQL. A model is involved only where a judgement is genuinely
    needed, and this asserts nobody quietly added another.

    ⚠ `candidate_analysis` is the third, and it earns its place on a narrow rule: which of
    India's structural bottlenecks a business solves is a judgement about what the business
    *is*, not a number. Every figure that follows from it — how many imperatives that
    bottleneck crosses, what multiple is defensible, the quality score itself — is computed
    from the framework and from filed accounts. And the model chooses from a closed list of 31
    ids, so it can place a company but cannot invent a place for one.
    """
    from app.jobs import all_jobs

    using_ai = sorted(j.name for j in all_jobs() if j.uses_ai)
    assert using_ai == ["candidate_analysis", "day_end_summary", "morning_brief"]


# --- a first boot is not a backlog of failures --------------------------------------


def test_a_jobs_first_ever_evaluation_is_never_a_miss(db, user, jobs_registry):
    """Found on the very first live tick. Deploying this feature at 01:52 wrote SIX `missed`
    rows, because every job's last scheduled moment was behind us — and nothing had been
    missed at all, because the jobs did not exist yet.

    Six failures on a healthy first boot is a bad first impression and worse evidence.
    "Missed" has to mean "it used to happen and this time it did not"."""

    @jobs_registry.job(
        f"{TEST_PREFIX}fresh",
        "0 21 * * *",
        description="brand new",
        catch_up=dt.timedelta(hours=3),
    )
    def _fresh(db_, user_):
        return JobResult()

    # 01:30, so yesterday's 21:00 is four and a half hours behind — outside the window.
    outcomes = runner.tick(db, user, at(2026, 8, 25, 1, 30))

    assert f"{TEST_PREFIX}fresh" not in outcomes
    assert _runs(db, f"{TEST_PREFIX}fresh") == []


def test_once_a_job_has_history_a_gap_IS_recorded(db, user, counting_job):
    """The other half of the same rule: a job that HAS run before and then does not is a
    real gap, and must leave a trace. Without this the fix above would silence the very
    signal it exists to preserve."""
    entry, _ = counting_job

    # Day one: it runs.
    assert runner.tick(db, user, at(2026, 8, 24, 21, 30))[entry.name] == "ok"
    # Day two: the machine was off until 01:30, past the three-hour window.
    assert runner.tick(db, user, at(2026, 8, 26, 1, 30))[entry.name] == "missed"

    statuses = [r.status for r in _runs(db, entry.name)]
    assert statuses == ["ok", "missed"]


def test_a_job_can_remind_against_an_existing_record(db, user, jobs_registry, fake_push):
    """The runner path for a situation that persists.

    A job must never deliver anything itself — the registry exists so that quiet hours, the
    ceiling, tracing and run recording are applied in one place rather than re-implemented
    per job. So a repeating reminder hands back the record it already raised and the runner
    re-delivers it, exactly as `notify` hands back a new one.
    """
    from app.db.models import PushSubscription
    from app.services import notifications

    from .conftest import make_subscription

    sub = make_subscription()
    db.add(PushSubscription(user_id=user.id, **sub))
    user.quiet_hours_start = user.quiet_hours_end = 0
    db.commit()

    row = notifications.raise_notification(
        db, user, NotificationSpec(kind="task_overdue", title="1 task is overdue", body="x")
    )
    assert row.push_count == 1

    @jobs_registry.job(f"{TEST_PREFIX}remind", "0 9 * * *", description="reminds")
    def _remind(db_, user_):
        return JobResult(
            remind=Reminder(record=row, title=row.title, body=row.body),
            detail={"reminder": 2},
        )

    status = runner.run_job(
        db, jobs_registry.get(f"{TEST_PREFIX}remind"), user, f"{TEST_PREFIX}remind-1"
    )

    db.refresh(row)
    assert status == "ok"
    assert row.push_count == 2, "the runner delivered it again"
    assert len(fake_push) == 2
    assert fake_push[-1][2]["Urgency"] == "high"
    assert (
        db.execute(select(Notification).where(Notification.user_id == user.id)).scalars().all()
    ) == [row], "one record, not two"
