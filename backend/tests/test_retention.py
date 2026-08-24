"""Retention: the traces must not outgrow the app they observe — and pruning them must
never cost the history.

The load-bearing property here is that spend figures are unchanged by pruning. Everything
else is hygiene; this is the part that would silently corrupt what the Insights page says.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.db.models import DailyUsage, Span, Turn
from app.services import insights, retention


def _turn(db, user, *, days_ago=0, **kw):
    row = Turn(
        user_id=user.id,
        kind=kw.pop("kind", "chat"),
        provider=kw.pop("provider", "openai"),
        model=kw.pop("model", "gpt-5.4-mini"),
        started_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago),
        duration_ms=kw.pop("duration_ms", 1000),
        ttft_ms=kw.pop("ttft_ms", 500),
        tokens_in=kw.pop("tokens_in", 100),
        tokens_out=kw.pop("tokens_out", 20),
        cost_usd=kw.pop("cost_usd", Decimal("0.001")),
        ok=kw.pop("ok", True),
        **kw,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _span(db, turn, name="llm_round1", ms=900):
    db.add(Span(turn_id=turn.id, name=name, seq=0, duration_ms=ms))
    db.commit()


def _rollup_rows(db, user):
    return db.execute(select(DailyUsage).where(DailyUsage.user_id == user.id)).scalars().all()


# --- the rollup ---------------------------------------------------------------------


def test_rollup_records_a_finished_day(db, user):
    _turn(db, user, days_ago=3, cost_usd=Decimal("0.002"), tokens_in=500)
    _turn(db, user, days_ago=3, cost_usd=Decimal("0.003"), tokens_in=700, ok=False)

    retention.rollup(db)

    rows = _rollup_rows(db, user)
    assert len(rows) == 1
    assert rows[0].calls == 2
    assert rows[0].failed == 1
    assert rows[0].cost_usd == Decimal("0.005000")
    assert rows[0].tokens_in == 1200


def test_today_is_not_rolled_up_while_it_is_still_happening(db, user):
    """A partial day written now would be wrong until the next sweep overwrote it, and the
    page reads today from the live turns anyway."""
    _turn(db, user, days_ago=0)

    retention.rollup(db)

    assert _rollup_rows(db, user) == []


def test_rollup_is_idempotent(db, user):
    """It runs opportunistically and may fire twice for the same day. Twice must not mean
    double."""
    _turn(db, user, days_ago=2, cost_usd=Decimal("0.004"))

    retention.rollup(db)
    retention.rollup(db)
    retention.rollup(db)

    rows = _rollup_rows(db, user)
    assert len(rows) == 1
    assert rows[0].calls == 1
    assert rows[0].cost_usd == Decimal("0.004000")


def test_a_late_arriving_turn_updates_the_day_it_belongs_to(db, user):
    _turn(db, user, days_ago=2, cost_usd=Decimal("0.001"))
    retention.rollup(db)
    _turn(db, user, days_ago=2, cost_usd=Decimal("0.005"))

    retention.rollup(db)

    rows = _rollup_rows(db, user)
    assert len(rows) == 1
    assert rows[0].calls == 2
    assert rows[0].cost_usd == Decimal("0.006000")


def test_a_null_model_still_gets_a_row(db, user):
    """Postgres treats NULLs as distinct in a unique constraint, so a nullable key column
    would insert a new row on every sweep instead of updating one."""
    _turn(db, user, days_ago=2, provider=None, model=None)

    retention.rollup(db)
    retention.rollup(db)

    rows = _rollup_rows(db, user)
    assert len(rows) == 1
    assert (rows[0].provider, rows[0].model) == ("unknown", "unknown")


# --- pruning ------------------------------------------------------------------------


def test_spans_are_pruned_while_their_turn_survives(db, user):
    old = _turn(db, user, days_ago=settings.span_retention_days + 5)
    recent = _turn(db, user, days_ago=1)
    _span(db, old)
    _span(db, recent)

    assert retention.prune_spans(db) == 1

    # Scoped to this test's turns: the dev database this suite runs against also holds real
    # traces, which a bare `select(Span)` would sweep up.
    mine = db.execute(select(Span).where(Span.turn_id.in_([old.id, recent.id]))).scalars().all()
    assert [s.turn_id for s in mine] == [recent.id]
    assert db.get(Turn, old.id) is not None  # the turn itself is kept far longer


def test_turns_are_not_pruned_before_the_rollup_covers_them(db, user):
    """The guard that makes the ordering safe. There is no backup, so a sweep that pruned
    first and rolled up second would destroy history permanently."""
    _turn(db, user, days_ago=settings.turn_retention_days + 5)

    assert retention.prune_turns(db) == 0  # nothing rolled up yet
    assert db.execute(select(Turn)).scalars().all()

    retention.rollup(db)
    assert retention.prune_turns(db) == 1


def test_sweep_rolls_up_before_it_prunes(db, user):
    _turn(db, user, days_ago=settings.turn_retention_days + 5, cost_usd=Decimal("0.009"))

    result = retention.sweep(db)

    assert result["turns_pruned"] == 1
    rows = _rollup_rows(db, user)
    assert len(rows) == 1 and rows[0].cost_usd == Decimal("0.009000")


def test_the_sweep_is_a_scheduled_job_not_a_side_effect_of_replying(db, user):
    """It used to run off the back of a delivered reply, gated by an in-memory date. That
    meant a quiet week pruned nothing, and the sweep took DELETE locks on `turns` while the
    app was in use. Both of those are the trigger's fault, not the sweep's — so the sweep is
    unchanged and only its trigger moved."""
    from app.core import telemetry
    from app.jobs import registry

    entry = registry.get("retention_sweep")
    assert entry is not None, "retention must be a registered job"
    assert entry.schedule == "15 3 * * *", "it should run at a quiet hour, not during use"
    assert entry.uses_ai is False

    # The opportunistic path is GONE, not merely unused. A dormant `maybe_sweep` would
    # invite a caller back.
    assert not hasattr(retention, "maybe_sweep")
    assert not hasattr(retention, "_last_run")
    assert not hasattr(telemetry, "_housekeeping")


def test_the_sweep_runs_however_late_it_is(db, user):
    """The opposite policy to a nudge. Sweeping late is strictly better than not sweeping at
    all, so this is the one job with no expiry — and it has to be spelled `None` rather than
    reached by choosing a large number.

    A large number would not even work: a window as long as the gap between occurrences can
    never expire, so `timedelta(days=7)` on a daily job silently means the same thing while
    reading like a limit. The registry now refuses that at import."""
    from app.jobs import registry

    assert registry.get("retention_sweep").catch_up is None


def test_a_failing_sweep_never_reaches_the_caller(db, user, monkeypatch):
    """A job that raises must be recorded and contained. Nothing about a failed sweep may
    reach the scheduler, another job, or the code serving the user."""
    from app.db.models import JobRun
    from app.jobs import registry, runner

    from .conftest import TEST_PREFIX

    monkeypatch.setattr(retention, "sweep", lambda _db: 1 / 0)
    entry = registry.get("retention_sweep")
    # Prefixed so the conftest purge removes it. Without the prefix the row survives the
    # test and the SECOND run of this test reports "duplicate" instead of running.
    key = f"{TEST_PREFIX}failing-sweep"

    status = runner.run_job(db, entry, user, key)

    assert status == "failed"
    row = db.execute(
        select(JobRun).where(JobRun.job_name == "retention_sweep", JobRun.occurrence_key == key)
    ).scalar_one()
    assert row.status == "failed"
    assert row.error_type == "ZeroDivisionError"


def test_notifications_are_pruned_too(db, user):
    """The notification history is the third table that only grows. Adding one in the same
    change that bounds the other two, and leaving it unbounded, would have been a poor joke."""
    import datetime as dt
    import uuid as _uuid

    from app.db.models import Notification

    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=settings.notification_retention_days + 5)
    recent = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    for created in (old, recent):
        db.add(
            Notification(
                id=_uuid.uuid4(),
                user_id=user.id,
                kind="test",
                title="t",
                body="b",
                created_at=created,
            )
        )
    db.commit()

    assert retention.prune_notifications(db) == 1
    left = db.execute(select(Notification).where(Notification.user_id == user.id)).scalars().all()
    assert len(left) == 1 and left[0].created_at > old


# --- the property that matters ------------------------------------------------------


def test_spend_history_survives_pruning(db, user):
    """Pruning is invisible in the numbers. The whole point of the rollup."""
    old_day = settings.turn_retention_days + 10
    _turn(db, user, days_ago=old_day, cost_usd=Decimal("0.700"), tokens_in=9000)
    _turn(db, user, days_ago=0, cost_usd=Decimal("0.010"), tokens_in=100)

    before = insights.summary(db, user.id)
    retention.sweep(db)
    after = insights.summary(db, user.id)

    live = db.execute(select(Turn).where(Turn.user_id == user.id)).scalars().all()
    assert len(live) == 1  # only today's turn survives; the old one was pruned
    assert after["cost_usd"] == before["cost_usd"] == Decimal("0.710")
    assert after["calls"] == before["calls"] == 2
    assert after["tokens_in"] == before["tokens_in"] == 9100

    # And the old day is still a point on the chart, not a gap.
    days = {p["day"] for p in insights.series(db, user.id)}
    assert len(days) == 2


def test_a_rolled_up_day_is_counted_once_not_twice(db, user):
    """Both tables hold recent days — the rollup is written long before the turns behind it
    are pruned. A rule based on "use the rollup where turns are missing" would count those
    days twice; a fixed boundary cannot."""
    _turn(db, user, days_ago=2, cost_usd=Decimal("0.050"))

    retention.rollup(db)  # the day now exists in BOTH tables
    assert _rollup_rows(db, user)
    assert db.execute(select(Turn)).scalars().all()

    assert insights.summary(db, user.id)["cost_usd"] == Decimal("0.050")
    assert insights.summary(db, user.id)["calls"] == 1


def test_by_model_still_attributes_spend_after_pruning(db, user):
    _turn(
        db,
        user,
        days_ago=settings.turn_retention_days + 10,
        model="gpt-5.5",
        cost_usd=Decimal("0.400"),
    )
    retention.sweep(db)

    rows = insights.by_model(db, user.id)
    assert [(r["model"], r["cost_usd"]) for r in rows] == [("gpt-5.5", Decimal("0.400"))]


def test_latency_percentiles_are_honestly_absent_for_pruned_periods(db, user):
    """A median cannot be re-derived from daily medians, so speed is only knowable while
    the turns are. Reporting a number here would be inventing one."""
    _turn(db, user, days_ago=settings.turn_retention_days + 10, duration_ms=5000)
    retention.sweep(db)

    s = insights.summary(db, user.id)
    assert s["calls"] == 1  # the call is still counted
    assert s["p50_ms"] is None  # its speed is not claimed


def test_a_rowcount_of_minus_one_is_not_counted_as_work(db, user):
    """`rowcount` is -1 when the driver cannot report one, and `or 0` does not catch it
    because -1 is truthy.

    Measured on the first live sweep: the rollup's INSERT..SELECT..ON CONFLICT returns
    exactly that, so the sweep recorded `{'rolled_up': -1}` and — worse — counted it as
    having done something, reporting `ok` where it should have reported `silent`.
    Pre-existing since the observability change; invisible until these counts started being
    written to `job_runs`."""

    class _Unreported:
        rowcount = -1

    class _None:
        rowcount = None

    class _Real:
        rowcount = 3

    assert retention._rows(_Unreported()) == 0
    assert retention._rows(_None()) == 0
    assert retention._rows(_Real()) == 3


def test_a_sweep_with_nothing_to_do_is_silent(db, user):
    """The consequence of the above, at the level that matters: a quiet night must read as
    `silent` in `job_runs`, not as `ok`. A column of `ok` for work that did nothing makes
    the record useless for spotting the night something actually happened."""
    from app.jobs import housekeeping

    result = housekeeping.retention_sweep(db, user)

    assert result.silent is True, result.detail
    assert all(v == 0 for v in result.detail.values()), result.detail
