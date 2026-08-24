"""Notifications: the record, the policy, and the delivery.

The push tests use a fake **transport**, not a fake sender. Encryption and VAPID signing
are real — only the HTTP POST is replaced — because those are the two parts most likely to
be subtly wrong and the two parts a naive mock would hide completely.
"""

import datetime as dt

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
    sub = db.execute(select(PushSubscription)).scalar_one()
    assert sub.last_error_at is not None
    assert sub.last_ok_at is None


def test_a_failing_push_is_recorded_against_the_device_not_the_work(db, user, loud, fake_push):
    """A phone left in a drawer must not make working software look broken."""
    _subscribe(db, user)
    fake_push.status = 503

    # `raise_notification` must not raise, whatever the push service does.
    notifications.raise_notification(db, user, spec())

    sub = db.execute(select(PushSubscription)).scalar_one()
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


def test_digests_get_a_longer_ttl_than_nudges(db, user, loud, fake_push):
    """A summary is worth holding for a day if the phone is off. A reminder about something
    time-sensitive is not."""
    _subscribe(db, user)

    notifications.raise_notification(db, user, spec(kind="day_end_summary"))
    notifications.raise_notification(db, user, spec(kind="task_overdue"))

    digest_ttl = int(fake_push[0][2]["TTL"])
    nudge_ttl = int(fake_push[1][2]["TTL"])
    assert digest_ttl == settings.push_ttl_digest_s
    assert nudge_ttl == settings.push_ttl_nudge_s
    assert digest_ttl > nudge_ttl


# --- dead subscriptions ------------------------------------------------------------------


@pytest.mark.parametrize("status", [404, 410])
def test_a_gone_subscription_is_deleted_not_retried(db, user, loud, fake_push, status):
    """A push service returns these once a browser is uninstalled or its storage cleared.
    Keeping them is how a notification system quietly gets slower every month."""
    _subscribe(db, user)
    fake_push.status = status

    notifications.raise_notification(db, user, spec())

    assert db.execute(select(PushSubscription)).scalars().all() == []


def test_a_transient_failure_keeps_the_subscription(db, user, loud, fake_push):
    _subscribe(db, user)
    fake_push.status = 500

    notifications.raise_notification(db, user, spec())

    assert len(db.execute(select(PushSubscription)).scalars().all()) == 1


def test_resubscribing_the_same_browser_updates_rather_than_duplicates(db, user):
    sub = make_subscription()
    notifications.subscribe(db, user.id, sub["endpoint"], sub["p256dh"], sub["auth"], "first")
    notifications.subscribe(db, user.id, sub["endpoint"], "NEWKEY", "NEWAUTH", "second")

    rows = db.execute(select(PushSubscription)).scalars().all()
    assert len(rows) == 1
    assert rows[0].p256dh == "NEWKEY"
    assert rows[0].user_agent == "second"


# --- policy ------------------------------------------------------------------------------


def test_quiet_hours_suppress_the_push_but_never_the_record(db, user, fake_push, monkeypatch):
    _subscribe(db, user)
    user.quiet_hours_start = 0
    user.quiet_hours_end = 23  # effectively always quiet, whatever time the suite runs
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
