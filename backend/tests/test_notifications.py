"""Notifications: the record, the policy, and the delivery.

The push tests use a fake **transport**, not a fake sender. Encryption and VAPID signing
are real — only the HTTP POST is replaced — because those are the two parts most likely to
be subtly wrong and the two parts a naive mock would hide completely.

⚠ Every query here is scoped to the test user, including the ones where it looks redundant.
The `push_subscriptions` assertions were originally unscoped — `select(PushSubscription)`
with no `WHERE` — and passed for as long as the development database happened to contain no
real subscriptions. The moment a real browser was registered locally in order to test push,
six of them began failing on that machine while CI stayed green, because they were counting
somebody's actual phone. A test that asserts about rows it did not create is asserting about
the developer's database, not about the code.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import settings
from app.core import push
from app.db.models import Notification, PushSubscription
from app.jobs.registry import Notification as NotificationSpec
from app.services import notifications

from .conftest import make_subscription


def spec(kind="test", **kw) -> NotificationSpec:
    return NotificationSpec(
        kind=kind,
        title=kw.get("title", "Something happened"),
        body=kw.get("body", "Details inside."),
        url=kw.get("url", "/#tasks"),
        tag=kw.get("tag"),
    )


def _subscribe(db, user) -> PushSubscription:
    sub = make_subscription()
    return notifications.subscribe(
        db, user.id, sub["endpoint"], sub["p256dh"], sub["auth"], "pytest"
    )


@pytest.fixture
def loud(db, user):
    """Turn quiet hours off for tests that assert a push happens.

    Without this the suite is TIME-DEPENDENT: the server default is 22:00-07:00, so every
    push test passes during the day and fails at night. Found exactly that way, at 1am.
    Equal values mean "no window" — see `notifications._quiet_window`.
    """
    user.quiet_hours_start = user.quiet_hours_end = 0
    db.commit()
    return user


# --- the record comes first -----------------------------------------------------------


def test_a_notification_is_recorded_before_any_delivery_is_attempted(db, user):
    """The rule the whole design rests on. With no VAPID keys configured — which is
    exactly the state of CI, and of a fresh checkout — delivery is impossible and the
    notification must still exist."""
    assert not push.configured()

    row = notifications.raise_notification(db, user, spec())

    stored = db.execute(select(Notification).where(Notification.id == row.id)).scalar_one()
    assert stored.title == "Something happened"
    assert stored.pushed_at is None
    assert stored.read_at is None


def test_a_notification_survives_a_failing_push(db, user, loud, fake_push, monkeypatch):
    _subscribe(db, user)
    fake_push.status = 500

    row = notifications.raise_notification(db, user, spec())

    assert row.pushed_at is None, "delivery failed"
    assert db.execute(select(Notification).where(Notification.id == row.id)).scalar_one()
    sub = db.execute(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    ).scalar_one()
    assert sub.last_error_at is not None
    assert sub.last_ok_at is None


def test_a_failing_push_is_recorded_against_the_device_not_the_work(db, user, loud, fake_push):
    """A phone left in a drawer must not make working software look broken."""
    _subscribe(db, user)
    fake_push.status = 503

    # `raise_notification` must not raise, whatever the push service does.
    notifications.raise_notification(db, user, spec())

    sub = db.execute(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    ).scalar_one()
    assert "503" in (sub.last_error or "")


# --- delivery ---------------------------------------------------------------------------


def test_a_successful_push_is_encrypted_signed_and_recorded(db, user, loud, fake_push):
    _subscribe(db, user)

    row = notifications.raise_notification(db, user, spec())

    assert row.pushed_at is not None
    assert len(fake_push) == 1
    endpoint, body, headers = fake_push[0]
    assert endpoint.startswith("https://fcm.googleapis.com/")
    # Real aes128gcm ciphertext — not the plaintext, and not empty.
    assert isinstance(body, bytes) and len(body) > 0
    assert b"Something happened" not in body, "the payload must be encrypted"
    assert headers["Content-Encoding"] == "aes128gcm"
    assert headers["Authorization"].startswith("WebPush ")
    assert int(headers["TTL"]) > 0


def test_the_payload_stays_well_under_the_size_limit(db, user, loud, fake_push):
    _subscribe(db, user)
    notifications.raise_notification(
        db, user, spec(title="A" * 100, body="B" * 300, url="/#journal/briefings")
    )
    _, body, _ = fake_push[0]
    assert len(body) < push.MAX_PAYLOAD_BYTES


def test_an_oversized_payload_is_refused_rather_than_sent(db, user, fake_push):
    """The 4 KB bound is the push services'. Discovering it at the far end means a silent
    non-delivery; discovering it here is an error someone can read."""
    sub = make_subscription()
    target = push.Subscription(sub["endpoint"], sub["p256dh"], sub["auth"])
    with pytest.raises(push.PushFailed, match="over the"):
        push.send(
            target,
            {"title": "x", "body": "y" * 5000},
            ttl=60,
            transport=lambda *a: 201,
        )


def test_the_ttl_is_the_producing_jobs_staleness_bound(db, user, loud, fake_push):
    """One declaration, both decisions.

    This replaces a test that asserted digests get a 24-hour TTL and nudges 4 hours, from a
    hand-maintained set of kind strings. That set disagreed with the jobs it described:
    `day_end_summary` declares `catch_up=3h` — "by midnight, so it still lands on the day it
    describes" — and was sent with instructions to hold it for a full day.
    """
    _subscribe(db, user)

    notifications.raise_notification(
        db, user, spec(kind="day_end_summary"), ttl=notifications.ttl_for(dt.timedelta(hours=3))
    )
    assert int(fake_push[-1][2]["TTL"]) == 3 * 3600

    notifications.raise_notification(
        db, user, spec(kind="task_overdue"), ttl=notifications.ttl_for(dt.timedelta(hours=1))
    )
    assert int(fake_push[-1][2]["TTL"]) == 3600


def test_work_with_no_staleness_bound_places_none_on_delivery(db, user, loud, fake_push):
    """`catch_up=None` means "however late" — retention is strictly better swept late than
    not swept. Its delivery says the same rather than quietly expiring in an hour."""
    _subscribe(db, user)
    notifications.raise_notification(db, user, spec(), ttl=notifications.ttl_for(None))
    assert int(fake_push[-1][2]["TTL"]) == notifications.MAX_TTL_S


def test_a_notification_no_job_produced_uses_the_default(db, user, loud, fake_push):
    """The test push from Settings has no job behind it and so no bound to inherit."""
    _subscribe(db, user)
    notifications.raise_notification(db, user, spec())
    assert int(fake_push[-1][2]["TTL"]) == settings.push_ttl_default_s


@pytest.mark.parametrize(
    "kind", ["day_end_summary", "morning_brief", "task_overdue", "journal_empty", "test"]
)
def test_every_notification_is_sent_as_time_critical(db, user, loud, fake_push, kind):
    """⚠ Asserts the HEADER the transport receives, not the constant — the constant agreeing
    with itself proves nothing.

    Measured in production on 2026-08-26: the day-end summary was dispatched at 21:03:12,
    zero seconds after its row was written, and reached the phone at roughly 21:40 when it
    was next unlocked. It had been sent `Urgency: low`, which asks the push service not to
    wake a dozing device. The server was never slow; it was asking to be ignored.
    """
    _subscribe(db, user)
    notifications.raise_notification(db, user, spec(kind=kind))
    assert fake_push[-1][2]["Urgency"] == "high"


# --- dead subscriptions ------------------------------------------------------------------


@pytest.mark.parametrize("status", [404, 410])
def test_a_gone_subscription_is_deleted_not_retried(db, user, loud, fake_push, status):
    """A push service returns these once a browser is uninstalled or its storage cleared.
    Keeping them is how a notification system quietly gets slower every month."""
    _subscribe(db, user)
    fake_push.status = status

    notifications.raise_notification(db, user, spec())

    assert (
        db.execute(select(PushSubscription).where(PushSubscription.user_id == user.id))
        .scalars()
        .all()
        == []
    )


def test_a_transient_failure_keeps_the_subscription(db, user, loud, fake_push):
    _subscribe(db, user)
    fake_push.status = 500

    notifications.raise_notification(db, user, spec())

    assert (
        len(
            db.execute(select(PushSubscription).where(PushSubscription.user_id == user.id))
            .scalars()
            .all()
        )
        == 1
    )


def test_resubscribing_the_same_browser_updates_rather_than_duplicates(db, user):
    sub = make_subscription()
    notifications.subscribe(db, user.id, sub["endpoint"], sub["p256dh"], sub["auth"], "first")
    notifications.subscribe(db, user.id, sub["endpoint"], "NEWKEY", "NEWAUTH", "second")

    rows = (
        db.execute(select(PushSubscription).where(PushSubscription.user_id == user.id))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].p256dh == "NEWKEY"
    assert rows[0].user_agent == "second"


# --- policy ------------------------------------------------------------------------------


def test_quiet_hours_suppress_the_push_but_never_the_record(db, user, fake_push, monkeypatch):
    _subscribe(db, user)
    # A one-hour window containing the current hour, derived rather than hard-coded.
    #
    # This used to be 0..23 with the comment "effectively always quiet, whatever time the
    # suite runs". It was not: the window is half-open, so hour 23 falls OUTSIDE it and the
    # test failed for exactly one hour a day. A test that is wrong for 1/24th of the clock
    # is worse than one that is always wrong, because it looks like flakiness in the code.
    #
    # Deriving it also exercises the midnight wrap for free once a day, at 23:00, since the
    # window then becomes 23..0 and takes the other branch of `in_quiet_hours`.
    hour = dt.datetime.now(ZoneInfo(settings.app_timezone)).hour
    user.quiet_hours_start = hour
    user.quiet_hours_end = (hour + 1) % 24
    db.commit()

    row = notifications.raise_notification(db, user, spec())

    assert row.pushed_at is None
    assert fake_push == [], "nothing should have been sent"
    assert db.execute(select(Notification).where(Notification.id == row.id)).scalar_one()


@pytest.mark.parametrize(
    ("start", "end", "hour", "quiet"),
    [
        (22, 7, 23, True),  # the wrapping window, after midnight-1
        (22, 7, 3, True),  # inside, after midnight
        (22, 7, 12, False),  # outside
        (22, 7, 7, False),  # end is exclusive
        (22, 7, 22, True),  # start is inclusive
        (9, 17, 12, True),  # a non-wrapping window
        (9, 17, 20, False),
    ],
)
def test_quiet_hours_handles_the_window_that_wraps_midnight(db, user, start, end, hour, quiet):
    """22:00-07:00 is the normal case and the one a naive `start <= hour < end` gets
    exactly backwards — it would be quiet from 7am to 10pm."""
    from zoneinfo import ZoneInfo

    user.quiet_hours_start, user.quiet_hours_end = start, end
    when = dt.datetime(2026, 8, 24, hour, 30, tzinfo=ZoneInfo(settings.app_timezone))
    assert notifications.in_quiet_hours(user, when) is quiet


def test_the_daily_cap_stops_interrupting_but_keeps_recording(db, user, loud, fake_push):
    _subscribe(db, user)
    user.daily_push_cap = 2
    db.commit()

    rows = [notifications.raise_notification(db, user, spec(tag=f"t{i}")) for i in range(4)]

    assert len(fake_push) == 2, "only the first two interrupt"
    assert sum(1 for r in rows if r.pushed_at is not None) == 2
    stored = db.execute(select(Notification).where(Notification.user_id == user.id)).scalars()
    assert len(list(stored)) == 4, "all four are recorded"


def test_a_test_notification_ignores_quiet_hours(db, user, fake_push):
    """The user asked for this one, so policy meant to prevent UNrequested interruptions
    does not apply."""
    _subscribe(db, user)
    user.quiet_hours_start, user.quiet_hours_end = 0, 23
    db.commit()

    row = notifications.raise_notification(db, user, spec(kind="test"), force_push=True)

    assert row.pushed_at is not None
    assert len(fake_push) == 1


# --- reading -----------------------------------------------------------------------------


def test_unread_count_and_marking(db, user):
    a = notifications.raise_notification(db, user, spec(title="one"))
    notifications.raise_notification(db, user, spec(title="two"))
    assert notifications.unread_count(db, user.id) == 2

    notifications.mark_read(db, user.id, a.id)
    assert notifications.unread_count(db, user.id) == 1

    assert notifications.mark_all_read(db, user.id) == 1
    assert notifications.unread_count(db, user.id) == 0


def test_marking_is_idempotent(db, user):
    a = notifications.raise_notification(db, user, spec())
    first = notifications.mark_read(db, user.id, a.id).read_at
    second = notifications.mark_read(db, user.id, a.id).read_at
    assert first == second


def test_notifications_are_listed_newest_first(db, user):
    notifications.raise_notification(db, user, spec(title="older"))
    notifications.raise_notification(db, user, spec(title="newer"))
    titles = [n.title for n in notifications.list_for_user(db, user.id)]
    assert titles[0] == "newer"


def test_quiet_hours_can_actually_be_turned_off(db, user):
    """NULL means "use the server default", so it cannot also mean "off". Equal values are
    the encoding for no window — without one, a user could never stop being quiet at
    night, and every push test in this file would depend on the wall clock."""
    user.quiet_hours_start = user.quiet_hours_end = None
    assert notifications.quiet_hours_enabled(user) is True, "defaults apply"

    user.quiet_hours_start = user.quiet_hours_end = 0
    assert notifications.quiet_hours_enabled(user) is False


# --- removal, and the two things it must NOT change ----------------------------------------
#
# Everywhere else, adding soft delete means "hide deleted rows from every query". There are
# exactly two exceptions, and both are here because getting either wrong is invisible until
# it has been annoying you for a week.


def test_a_removed_notification_is_invisible_to_every_reader(db, user):
    row = notifications.raise_notification(db, user, spec(title="Gone"))
    assert notifications.unread_count(db, user.id) == 1

    notifications.delete_notification(db, user.id, row.id)

    assert [n.id for n in notifications.list_for_user(db, user.id)] == []
    assert notifications.unread_count(db, user.id) == 0, (
        "a removed unread must not keep the badge lit"
    )
    assert notifications.mark_read(db, user.id, row.id) is None, "gone means gone"


def test_a_removed_notification_comes_back_with_the_same_identity(db, user):
    row = notifications.raise_notification(db, user, spec(title="Back"))
    notifications.delete_notification(db, user.id, row.id)

    restored = notifications.restore_notification(db, user.id, row.id)

    assert restored is not None and restored.id == row.id
    assert restored.title == "Back"
    assert [n.id for n in notifications.list_for_user(db, user.id)] == [row.id]


def test_removing_a_notification_does_not_make_the_nudge_repeat(db, user):
    """⚠ THE invariant. `already_said` asks what has been SAID, not what is still on screen.

    Filter deleted rows out of it and dismissing "3 tasks are overdue" erases the evidence
    that it was ever said — so the next hourly run treats an unchanged situation as news and
    pushes it again. Delete would silently acquire the meaning "remind me within the hour",
    on precisely the notification most likely to be dismissed.
    """
    row = notifications.raise_notification(db, user, spec(kind="task_overdue", tag="overdue-abc"))
    assert notifications.already_said(db, user.id, "task_overdue", "overdue-abc")

    notifications.delete_notification(db, user.id, row.id)

    assert notifications.already_said(db, user.id, "task_overdue", "overdue-abc"), (
        "dismissing a notification must not re-arm the nudge behind it"
    )


def test_removing_a_delivered_notification_does_not_reduce_the_days_count(
    db, user, loud, fake_push
):
    """The second exception. A count of deliveries is a count of DELIVERIES, not of
    surviving receipts — the phone already buzzed."""
    _subscribe(db, user)
    row = notifications.raise_notification(db, user, spec())
    assert row.pushed_at is not None
    assert notifications.pushed_today(db, user.id) == 1

    notifications.delete_notification(db, user.id, row.id)

    assert notifications.pushed_today(db, user.id) == 1


def test_a_notification_that_never_reached_a_device_never_counted(db, user):
    """Recorded but undelivered contributes nothing, before or after removal — so the two
    exceptions cannot be confused with "count everything ever written"."""
    row = notifications.raise_notification(db, user, spec())
    assert row.pushed_at is None
    assert notifications.pushed_today(db, user.id) == 0

    notifications.delete_notification(db, user.id, row.id)
    assert notifications.pushed_today(db, user.id) == 0


def test_clear_read_removes_only_read_rows_and_reports_exactly_which(db, user):
    read_one = notifications.raise_notification(db, user, spec(title="read one"))
    read_two = notifications.raise_notification(db, user, spec(title="read two"))
    unread = notifications.raise_notification(db, user, spec(title="still unread"))
    notifications.mark_read(db, user.id, read_one.id)
    notifications.mark_read(db, user.id, read_two.id)

    cleared = notifications.clear_read(db, user.id)

    assert set(cleared) == {read_one.id, read_two.id}
    assert [n.id for n in notifications.list_for_user(db, user.id)] == [unread.id]


def test_undo_restores_exactly_what_was_cleared_and_nothing_else(db, user):
    """Why `clear_read` returns ids rather than a count.

    "Restore everything read" is the obvious inverse and is wrong: anything marked read
    between the clear and the undo would be resurrected too — rows the user never deleted.
    """
    old = notifications.raise_notification(db, user, spec(title="cleared"))
    notifications.mark_read(db, user.id, old.id)
    cleared = notifications.clear_read(db, user.id)

    # The user reads something else before pressing undo.
    later = notifications.raise_notification(db, user, spec(title="read in the meantime"))
    notifications.mark_read(db, user.id, later.id)

    notifications.restore_notifications(db, user.id, cleared)

    live = {n.id for n in notifications.list_for_user(db, user.id)}
    assert live == {old.id, later.id}
    assert later.deleted_at is None, "it was never deleted, so undo must not have touched it"


def test_with_the_default_settings_nothing_is_ever_withheld_for_volume(db, user, loud, fake_push):
    """Pins the removal of the ceiling, so it cannot come back by accident.

    It used to default to 6 while `task_nudge` alone can fire seven times a day, which meant
    it was discarding notifications that were wanted — starting with the repeating overdue
    ping, the one most explicitly asked for.
    """
    _subscribe(db, user)
    for i in range(12):
        row = notifications.raise_notification(db, user, spec(title=f"number {i}"))
        assert row.pushed_at is not None, f"notification {i} was withheld"
    assert notifications.pushed_today(db, user.id) == 12


def test_a_ceiling_still_works_when_one_is_deliberately_set(db, user, loud, fake_push):
    """The mechanism is retained rather than deleted: per-tag suppression is no defence at
    all against a job that loops, and this is the only bound such a job would respect."""
    _subscribe(db, user)
    user.daily_push_cap = 2
    db.commit()

    delivered = [
        notifications.raise_notification(db, user, spec(title=f"n{i}")).pushed_at for i in range(4)
    ]

    assert sum(1 for d in delivered if d is not None) == 2
    assert delivered[2] is None and delivered[3] is None


# --- already_said and its time bound -------------------------------------------------------


def test_already_said_without_a_window_looks_back_forever(db, user):
    """Correct for a tag that encodes a CHANGING SET — the overdue-task fingerprint stops
    matching by itself the moment the situation changes, so a bound would only re-announce
    something unchanged."""
    row = notifications.raise_notification(db, user, spec(kind="task_overdue", tag="t1"))
    row.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=400)
    db.commit()

    assert notifications.already_said(db, user.id, "task_overdue", "t1")


def test_already_said_with_a_window_ignores_anything_older(db, user):
    """Required for a tag that can RECUR — a disk band. Without the bound, crossing 80%
    once would be reported once in the lifetime of the installation: free some space, drift
    back up a month later, and a year-old row silences it forever."""
    row = notifications.raise_notification(db, user, spec(kind="disk", tag="disk-80"))
    row.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=30)
    db.commit()

    assert not notifications.already_said(
        db, user.id, "disk", "disk-80", since=dt.timedelta(hours=24)
    )
    assert notifications.already_said(db, user.id, "disk", "disk-80"), (
        "without the window it is still found — both halves must hold, or the parameter "
        "could be silently doing nothing"
    )


# --- repeat delivery (migration 013) -------------------------------------------------------


def test_urgency_does_not_defeat_quiet_hours(db, user, fake_push):
    """Every notification is now sent time-critical, and that must not have quietly become a
    way to buzz someone at 3am.

    Urgency is a request to the push service about how to reach a SLEEPING DEVICE. Whether
    the user wants to be reached at all is a different decision, made earlier and by them.
    """
    _subscribe(db, user)
    hour = dt.datetime.now(ZoneInfo(settings.app_timezone)).hour
    user.quiet_hours_start, user.quiet_hours_end = hour, (hour + 1) % 24
    db.commit()

    row = notifications.raise_notification(db, user, spec(kind="task_overdue"))

    assert fake_push == [], "urgency must not become an override for the user's own policy"
    assert row.pushed_at is None
    assert row.push_count == 0


def test_a_delivered_record_counts_one_delivery(db, user, loud, fake_push):
    _subscribe(db, user)
    row = notifications.raise_notification(db, user, spec())
    assert row.pushed_at is not None
    assert row.push_count == 1


def test_an_undelivered_record_counts_none(db, user):
    """The counter starts at zero, which is why migration 013 does not default it to 1: the
    row is written BEFORE delivery is attempted, so a default of 1 would claim an
    interruption that never happened."""
    row = notifications.raise_notification(db, user, spec())
    assert row.pushed_at is None
    assert row.push_count == 0


def test_delivering_again_reuses_the_record_and_counts_the_buzz(db, user, loud, fake_push):
    """The shape the overdue nudge relies on: one record, many interruptions."""
    _subscribe(db, user)
    row = notifications.raise_notification(db, user, spec(kind="task_overdue"))
    first_seen = row.created_at

    for expected in (2, 3, 4):
        assert notifications.deliver_again(db, user, row) is True
        assert row.push_count == expected

    assert len(fake_push) == 4, "each reminder is a real send"
    assert row.created_at == first_seen, (
        "created_at says when the situation BEGAN — 'overdue since 10:03' is the useful "
        "fact, and moving it would destroy that to gain nothing"
    )
    assert len(notifications.list_for_user(db, user.id)) == 1, "one record, not four"


def test_delivering_again_obeys_quiet_hours(db, user, loud, fake_push):
    """Being told once already does not stop quiet hours applying to the reminder."""
    _subscribe(db, user)
    row = notifications.raise_notification(db, user, spec(kind="task_overdue"))
    assert row.push_count == 1

    hour = dt.datetime.now(ZoneInfo(settings.app_timezone)).hour
    user.quiet_hours_start, user.quiet_hours_end = hour, (hour + 1) % 24
    db.commit()

    assert notifications.deliver_again(db, user, row) is False
    assert row.push_count == 1, "a suppressed reminder is not a delivery"


def test_the_days_count_counts_deliveries_not_records(db, user, loud, fake_push):
    """⚠ Load-bearing. A ceiling is measured against this, so counting ROWS would report
    seven buzzes as one and a ceiling of 2 would never be reached by a repeating nudge."""
    _subscribe(db, user)
    row = notifications.raise_notification(db, user, spec(kind="task_overdue"))
    notifications.deliver_again(db, user, row)
    notifications.deliver_again(db, user, row)

    assert len(notifications.list_for_user(db, user.id)) == 1
    assert notifications.pushed_today(db, user.id) == 3


def test_a_ceiling_counts_repeat_deliveries_against_itself(db, user, loud, fake_push):
    _subscribe(db, user)
    user.daily_push_cap = 2
    db.commit()

    row = notifications.raise_notification(db, user, spec(kind="task_overdue"))
    assert row.push_count == 1
    assert notifications.deliver_again(db, user, row) is True
    assert notifications.deliver_again(db, user, row) is False, "the ceiling applies to buzzes"
    assert row.push_count == 2


def test_removing_a_repeated_record_still_does_not_reduce_the_count(db, user, loud, fake_push):
    """The migration-012 invariant, restated for a record delivered many times."""
    _subscribe(db, user)
    row = notifications.raise_notification(db, user, spec(kind="task_overdue"))
    notifications.deliver_again(db, user, row)
    notifications.delete_notification(db, user.id, row.id)

    assert notifications.pushed_today(db, user.id) == 2


# --- todays_record -------------------------------------------------------------------------


def test_todays_record_finds_the_live_record_for_this_situation(db, user):
    row = notifications.raise_notification(db, user, spec(kind="task_overdue", tag="overdue-a"))
    found = notifications.todays_record(db, user.id, "task_overdue", "overdue-a")
    assert found is not None and found.id == row.id


def test_todays_record_ignores_a_different_situation(db, user):
    notifications.raise_notification(db, user, spec(kind="task_overdue", tag="overdue-a"))
    assert notifications.todays_record(db, user.id, "task_overdue", "overdue-b") is None


def test_todays_record_ignores_a_removed_record(db, user):
    """Removing today's reminder must not silence the situation, and must not resurrect the
    row either. The next check writes a fresh record instead."""
    row = notifications.raise_notification(db, user, spec(kind="task_overdue", tag="overdue-a"))
    notifications.delete_notification(db, user.id, row.id)
    assert notifications.todays_record(db, user.id, "task_overdue", "overdue-a") is None


def test_todays_record_ignores_yesterdays(db, user):
    """Why the bound is a day.

    The panel is ordered `created_at DESC`. Without this, a task overdue for three weeks
    would hold a three-week-old record at the bottom of a fifty-row list while the phone
    buzzed about it every two hours — invisible in the very application doing the nudging.
    """
    row = notifications.raise_notification(db, user, spec(kind="task_overdue", tag="overdue-a"))
    row.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    db.commit()
    assert notifications.todays_record(db, user.id, "task_overdue", "overdue-a") is None


def test_a_reminder_can_refresh_the_wording_without_becoming_a_new_record(
    db, user, loud, fake_push
):
    """Renaming the thing a reminder is about must change what the reminder says.

    The tag pins WHICH situation this is; the wording describes it as it reads now. Without
    this, a renamed overdue task would be reminded about under its old name until midnight.
    """
    _subscribe(db, user)
    row = notifications.raise_notification(
        db, user, spec(kind="task_overdue", title="1 task is overdue", body="buy gifts")
    )
    created = row.created_at

    notifications.deliver_again(db, user, row, title="1 task is overdue", body="buy more gifts")

    assert row.body == "buy more gifts"
    assert row.created_at == created, "identity and start time are untouched"
    assert row.push_count == 2
    assert len(notifications.list_for_user(db, user.id)) == 1


def test_a_reminder_is_paced_by_time_since_the_last_delivery(db, user, loud, fake_push):
    _subscribe(db, user)
    row = notifications.raise_notification(db, user, spec(kind="task_overdue"))

    assert notifications.reminder_is_due(row, dt.timedelta(hours=2)) is False
    row.pushed_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2, seconds=1)
    db.commit()
    assert notifications.reminder_is_due(row, dt.timedelta(hours=2)) is True


def test_an_undelivered_record_is_always_due_for_a_reminder(db, user):
    """Pacing measures time since the last INTERRUPTION, and a record suppressed by quiet
    hours has interrupted nobody."""
    row = notifications.raise_notification(db, user, spec(kind="task_overdue"))
    assert row.pushed_at is None
    assert notifications.reminder_is_due(row, dt.timedelta(hours=2)) is True
