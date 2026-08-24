"""The notification and job routes.

Two properties get disproportionate attention here, and both are security rather than
tidiness:

  - **Every route requires authentication.** A push subscription is a capability to
    interrupt someone; an endpoint that could be registered or read without a session
    would be a real hole.
  - **The VAPID private key never leaves the server.** The public half is served on
    purpose, so a test that merely checked "no key in the response" would be wrong. It has
    to check that the *private* one is absent while the public one is present.
"""

import pytest
from sqlalchemy import select

from app.db.models import Notification, PushSubscription
from app.jobs.registry import Notification as NotificationSpec
from app.services import notifications

from .conftest import make_subscription


def _raise(db, user, title="Something happened", kind="test"):
    return notifications.raise_notification(
        db, user, NotificationSpec(kind=kind, title=title, body="Details.", url="/#tasks")
    )


# --- authentication -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/notifications"),
        ("get", "/api/notifications/unread"),
        ("post", "/api/notifications/read-all"),
        ("get", "/api/notifications/push"),
        ("post", "/api/notifications/push"),
        ("delete", "/api/notifications/push?endpoint=x"),
        ("post", "/api/notifications/push/test"),
        ("get", "/api/jobs"),
        ("patch", "/api/jobs/task_nudge"),
        ("get", "/api/journal/briefings"),
    ],
)
def test_every_route_requires_a_session(client, method, path):
    # `request` rather than `client.get(..., json=...)` — httpx refuses a body on GET and
    # DELETE, which would make this fail with a TypeError instead of asserting anything.
    response = client.request(method.upper(), path, json={})
    assert response.status_code == 401, path


# --- reading --------------------------------------------------------------------------


def test_listing_returns_notifications_and_the_unread_count(auth_client, db, user):
    _raise(db, user, "first")
    _raise(db, user, "second")

    body = auth_client.get("/api/notifications").json()

    assert body["unread"] == 2
    assert [n["title"] for n in body["items"]] == ["second", "first"]
    assert body["items"][0]["url"] == "/#tasks"


def test_unread_is_a_cheap_separate_endpoint(auth_client, db, user):
    """Polled by the bell on every page load, so it must not have to serialise rows."""
    _raise(db, user)
    assert auth_client.get("/api/notifications/unread").json() == {"unread": 1}


def test_marking_one_read(auth_client, db, user):
    row = _raise(db, user)
    response = auth_client.post(f"/api/notifications/{row.id}/read")
    assert response.status_code == 200
    assert response.json()["read_at"] is not None
    assert auth_client.get("/api/notifications/unread").json()["unread"] == 0


def test_marking_all_read(auth_client, db, user):
    _raise(db, user)
    _raise(db, user)
    assert auth_client.post("/api/notifications/read-all").json() == {"marked": 2}
    assert auth_client.get("/api/notifications/unread").json()["unread"] == 0


def test_another_users_notification_cannot_be_marked(auth_client, db, user):
    """Ownership is enforced on the route, not assumed from the id being unguessable."""
    from app.core.security import hash_password
    from app.db.models import User

    from .conftest import OTHER_EMAIL

    other = User(email=OTHER_EMAIL, password_hash=hash_password("x"))
    db.add(other)
    db.commit()
    theirs = _raise(db, other)

    assert auth_client.post(f"/api/notifications/{theirs.id}/read").status_code == 404
    assert db.get(Notification, theirs.id).read_at is None


def test_a_missing_notification_is_a_404_not_a_crash(auth_client):
    import uuid

    assert auth_client.post(f"/api/notifications/{uuid.uuid4()}/read").status_code == 404


# --- push subscriptions ----------------------------------------------------------------


def test_push_status_serves_the_public_key_and_never_the_private_one(
    auth_client, db, user, fake_push
):
    from app.config import settings

    body = auth_client.get("/api/notifications/push").json()

    assert body["configured"] is True
    assert body["public_key"] == settings.vapid_public_key
    # The whole point. The public half is meant to be here; the private half must not be
    # anywhere in the payload, under any key name.
    serialised = str(body)
    assert settings.vapid_private_key not in serialised
    assert not any("private" in k.lower() for k in body)


def test_push_status_is_honest_when_the_server_has_no_keys(auth_client):
    body = auth_client.get("/api/notifications/push").json()
    assert body["configured"] is False
    assert body["public_key"] == ""
    assert body["devices"] == 0


def test_subscribing_registers_the_device(auth_client, db, user):
    response = auth_client.post("/api/notifications/push", json=make_subscription())

    assert response.status_code == 201
    assert response.json()["devices"] == 1
    row = db.execute(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    ).scalar_one()
    assert row.user_agent, "the user agent is stored so two devices are distinguishable"


def test_unsubscribing_removes_it(auth_client, db, user):
    sub = make_subscription()
    auth_client.post("/api/notifications/push", json=sub)

    response = auth_client.request(
        "DELETE", "/api/notifications/push", params={"endpoint": sub["endpoint"]}
    )

    assert response.json() == {"ok": True, "devices": 0}


def test_a_subscription_payload_carries_no_server_secret(auth_client):
    """`p256dh` and `auth` are the BROWSER's keys, generated by it for this origin. Nothing
    of ours travels in this direction, which is why the endpoint accepts exactly three
    fields and ignores anything else."""
    from app.api.schemas import PushSubscribeIn

    assert set(PushSubscribeIn.model_fields) == {"endpoint", "p256dh", "auth"}


# --- the test notification ---------------------------------------------------------------


def test_the_test_notification_explains_itself_when_it_cannot_send(auth_client, db, user):
    """Push involves five parties and four are somebody else's. Every refusal here has to
    say WHICH one, or a silent non-delivery costs an evening to diagnose."""
    body = auth_client.post("/api/notifications/push/test").json()
    assert body["ok"] is False
    assert "VAPID" in body["reason"]


def test_the_test_notification_reports_a_missing_device(auth_client, db, user, fake_push):
    body = auth_client.post("/api/notifications/push/test").json()
    assert body["ok"] is False
    assert "subscribed" in body["reason"]


def test_the_test_notification_sends(auth_client, db, user, fake_push):
    auth_client.post("/api/notifications/push", json=make_subscription())
    user.quiet_hours_start = user.quiet_hours_end = 0
    db.commit()

    assert auth_client.post("/api/notifications/push/test").json() == {"ok": True}
    assert len(fake_push) == 1


def test_the_test_notification_ignores_quiet_hours(auth_client, db, user, fake_push):
    """The user asked for this one, so a policy meant to stop UNrequested interruptions
    does not apply — otherwise the diagnostic tool is broken exactly when it is needed."""
    auth_client.post("/api/notifications/push", json=make_subscription())
    user.quiet_hours_start, user.quiet_hours_end = 0, 23
    db.commit()

    assert auth_client.post("/api/notifications/push/test").json()["ok"] is True


# --- jobs ---------------------------------------------------------------------------------


def test_listing_jobs_describes_each_one_in_plain_language(auth_client):
    jobs = auth_client.get("/api/jobs").json()

    assert len(jobs) >= 6
    by_name = {j["name"]: j for j in jobs}
    assert by_name["day_end_summary"]["when"] == "every day at 21:00"
    assert by_name["task_nudge"]["when"] == "hourly between 09:00 and 21:00"
    for job in jobs:
        assert job["description"].strip()
        assert job["schedule"], "the raw expression is the truth"
        assert job["when"], "the phrase is what a person reads"


def test_a_jobs_default_state_is_reported(auth_client):
    by_name = {j["name"]: j for j in auth_client.get("/api/jobs").json()}
    assert by_name["journal_nudge"]["default_on"] is False
    assert by_name["journal_nudge"]["enabled"] is False
    assert by_name["day_end_summary"]["enabled"] is True


def test_toggling_a_job_persists(auth_client):
    response = auth_client.patch("/api/jobs/journal_nudge", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True

    by_name = {j["name"]: j for j in auth_client.get("/api/jobs").json()}
    assert by_name["journal_nudge"]["enabled"] is True


def test_toggling_an_unknown_job_is_refused(auth_client):
    """A preference for a job that does not exist is indistinguishable afterwards from a
    job that was removed, and would sit in the table forever looking meaningful."""
    assert auth_client.patch("/api/jobs/no-such-job", json={"enabled": True}).status_code == 404


def test_there_is_no_route_that_triggers_a_job(client):
    """Running work on demand from the browser turns a scheduler into a remote execution
    endpoint. The legitimate need is served by `python -m app.jobs.run`, which requires
    shell access to the machine."""
    with client as c:
        paths = c.get("/openapi.json").json()["paths"]
    triggers = [p for p in paths if p.startswith("/api/jobs") and "run" in p.lower()]
    assert triggers == []


# --- briefings ------------------------------------------------------------------------------


def test_briefings_are_listed_newest_first(auth_client, db, user):
    import datetime as dt

    from app.db.models import GeneratedReview

    for day in (23, 24):
        start = dt.datetime(2026, 8, day, tzinfo=dt.UTC)
        db.add(
            GeneratedReview(
                user_id=user.id,
                kind="daily",
                period_start=start,
                period_end=start + dt.timedelta(days=1),
                content=f"day {day}",
                delivered_to=[],
            )
        )
    db.commit()

    rows = auth_client.get("/api/journal/briefings").json()
    assert [r["content"] for r in rows] == ["day 24", "day 23"]


def test_briefings_are_scoped_to_the_user(auth_client, db, user):
    import datetime as dt

    from app.core.security import hash_password
    from app.db.models import GeneratedReview, User

    from .conftest import OTHER_EMAIL

    other = User(email=OTHER_EMAIL, password_hash=hash_password("x"))
    db.add(other)
    db.commit()
    now = dt.datetime.now(dt.UTC)
    db.add(
        GeneratedReview(
            user_id=other.id,
            kind="daily",
            period_start=now,
            period_end=now,
            content="not yours",
            delivered_to=[],
        )
    )
    db.commit()

    assert auth_client.get("/api/journal/briefings").json() == []
