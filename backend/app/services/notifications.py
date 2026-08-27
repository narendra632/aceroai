"""What the system has to say, and how it gets said.

The rule this module exists to enforce:

    **Write the row. Then attempt delivery. Never the reverse.**

A push notification is not a record — it is swiped off a lockscreen, refused permission,
or delivered to a laptop that is closed. A system whose only memory of "two tasks are
overdue" is a toast you dismissed while walking is not a system that reduces what you have
to remember. So the row is written first and unconditionally, and push is one way of drawing
attention to a row that already exists.

Two consequences follow, and both are deliberate:

- **A suppressed notification is still written.** Quiet hours stop the interruption, not the
  record. It is waiting in the app in the morning.
- **A failed push is not failed work.** The job that raised it is `ok`; the failure is
  recorded against the subscription. Conflating them would make a phone left in a drawer
  look like broken software.

A third rule was added when notifications became deletable (migration 012):

- **Removing the record of something said does not make it unsaid.** Every reader here that
  LISTS notifications filters `deleted_at`; the two that ask what has already HAPPENED —
  `pushed_today` and `already_said` — deliberately do not. Making them
  consistent with the rest would turn dismissing a nudge into a request to be nudged again.

And a fourth when a record became repeatable (migration 013):

- **One record may be delivered many times.** A reminder that persists — an overdue task —
  buzzes every two hours against a single record for the day rather than writing a record per
  buzz. `pushed_at` therefore means *last* delivered, and `push_count` is how many times.
  Anything counting interruptions counts deliveries, not rows.
"""

import datetime as dt
import logging
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import push
from app.db.models import Notification, PushSubscription, User
from app.jobs.registry import Notification as NotificationSpec

log = logging.getLogger(__name__)

# How time-critical every notification this application sends is. RFC 8030 defines four
# levels as the minimum device state at which a message is worth delivering — `very-low` for
# advertisements, `low` for topic updates, `normal` for chat, `high` for a time-sensitive
# alert — and on Android anything below `high` may be held while the device is dozing and
# released only when it is next picked up.
#
# **A constant, not a per-kind table.** This application has no advertisement tier: every
# notification it sends is one the user scheduled and is waiting for. A summary of the user's
# day has its entire value in arriving at the end of that day.
#
# There WAS a per-kind table here, marking digests `low`. Measured in production on
# 2026-08-26: the day-end summary was dispatched at 21:03:12, zero seconds after its row was
# written, and reached the phone at roughly 21:40 when it was next unlocked. The server was
# never slow. It was politely asking to be ignored, and the push service obliged.
#
# This does NOT override quiet hours. Urgency tells the push service how to reach a sleeping
# device; whether the user wants to be reached at all is decided earlier, in
# `_suppression_reason`.
URGENCY = "high"


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def _quiet_window(user: User) -> tuple[int, int] | None:
    """The user's quiet window, or None when there is not one.

    NULL on either column means "not configured" and falls back to the server default, so
    a fresh account gets sensible quiet hours without having to choose them.

    **Equal values mean OFF.** A zero-length window is no window, and this is the only
    encoding available: NULL is already taken by "use the default", so without it the user
    could never actually turn quiet hours off. The Settings UI writes 0/0 for "off".
    """
    start = (
        user.quiet_hours_start if user.quiet_hours_start is not None else settings.quiet_hours_start
    )
    end = user.quiet_hours_end if user.quiet_hours_end is not None else settings.quiet_hours_end
    if start is None or end is None or start == end:
        return None
    return start, end


def quiet_hours_enabled(user: User) -> bool:
    """Whether a quiet window applies at all. Used by Settings to render the toggle."""
    return _quiet_window(user) is not None


def in_quiet_hours(user: User, when: dt.datetime | None = None) -> bool:
    """Whether `when` falls inside the user's quiet window.

    Handles the window that wraps midnight (22:00-07:00), which is the normal case and the
    one an obvious `start <= hour < end` gets wrong.
    """
    window = _quiet_window(user)
    if window is None:
        return False
    start, end = window
    hour = (when or dt.datetime.now(_tz())).astimezone(_tz()).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def pushed_today(db: Session, user_id: uuid.UUID) -> int:
    """How many notifications reached a device today.

    ⚠ **Deliberately does not filter `deleted_at`**, unlike every reader that lists rows.

    This counts *deliveries*, not surviving records. The phone already buzzed; removing the
    note about it does not un-buzz it, so a count that dropped when the user tidied their
    panel would simply be a wrong answer to "how many times has this interrupted me today".

    It is also what a deliberately-set ceiling is measured against (`_cap`), which makes the
    distinction load-bearing rather than cosmetic: were this filtered, clearing the panel
    would silently re-arm delivery, and the tidier the user kept their notifications the more
    they would be interrupted.

    ⚠ **Sums `push_count` rather than counting rows** (migration 013). One record can now be
    delivered repeatedly — the overdue nudge reminds against a single record for the day — so
    counting rows would report seven buzzes as one, and a ceiling measured against it would
    be measuring the wrong thing entirely.

    Public rather than underscored because Settings now displays it.
    """
    midnight = dt.datetime.now(_tz()).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.execute(
            select(func.coalesce(func.sum(Notification.push_count), 0)).where(
                Notification.user_id == user_id,
                Notification.pushed_at.is_not(None),
                Notification.pushed_at >= midnight,
            )
        ).scalar_one()
        or 0
    )


def _cap(user: User) -> int:
    """The ceiling on deliveries per day. **Zero means no ceiling, and is the default.**

    The ceiling used to default to 6 while `task_nudge` alone can fire seven times a day, so
    it was binding in ordinary use — which means it was silently discarding notifications the
    user wanted, starting with the most frequent ones. A limit reached during normal operation
    is not a safety limit; it is an undocumented feature that stops telling you things after
    lunch.

    Volume is governed by the nature of the subject, which is the right control for expected
    volume. For most subjects that means the per-tag suppression in `jobs/nudges.py` — a
    measurement still inside the band it was reported in is not news. For a subject the user
    has to ACT on, it means repeating until they do; `task_nudge` reminds every two hours
    until the task is dealt with or rescheduled, and that repetition is the feature.

    The mechanism is kept rather than deleted because it is the wrong control for *unexpected*
    volume, and that is a real failure mode: a job that loops, or one whose tag changes every
    run, is not touched by per-tag suppression at all. A setting that is zero costs one falsy
    check and is the difference between a bad hour and a bad hour with no way to stop it.
    """
    return user.daily_push_cap if user.daily_push_cap is not None else settings.daily_push_cap


def raise_notification(
    db: Session,
    user: User,
    spec: NotificationSpec,
    *,
    job_name: str | None = None,
    ttl: int | None = None,
    force_push: bool = False,
) -> Notification:
    """Record a notification and try to deliver it. Returns the stored row.

    Never raises. A notification that cannot be delivered is still a notification that
    happened, and the caller — usually a job — must not be failed by a phone.

    `ttl` is how long the push service should hold this for an offline device. A scheduled
    job passes its own staleness bound (see `ttl_for`); anything else leaves it None and gets
    the configured default.
    """
    row = Notification(
        id=uuid.uuid4(),
        user_id=user.id,
        kind=spec.kind,
        title=spec.title,
        body=spec.body,
        url=spec.url,
        tag=spec.tag,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    reason = _suppression_reason(db, user, spec, force_push=force_push)
    if reason is not None:
        log.info("notification %s recorded but not pushed: %s", spec.kind, reason)
        return row

    if deliver(db, user, spec, ttl=ttl):
        _record_delivery(db, row)
    return row


def reminder_is_due(row: Notification, every: dt.timedelta) -> bool:
    """Whether enough time has passed to interrupt about this record again.

    **This is what separates how fast you FIND OUT from how often you are REMINDED**, and the
    two are different numbers that were briefly the same one. Running the check every two
    hours meant a task that fell due at 11:05 went unmentioned until 13:03 — the repetition
    interval had silently become the detection delay as well.

    The check now runs hourly and this paces the interruptions, so a new situation is found
    within the hour while an unchanged one still only buzzes every couple of hours.

    A record that has never been delivered is always due: it has not interrupted anyone yet,
    so there is nothing to pace. That is what makes a reminder held back by quiet hours reach
    the user once the window ends.
    """
    if row.pushed_at is None:
        return True
    return dt.datetime.now(dt.UTC) - row.pushed_at >= every


def deliver_again(
    db: Session,
    user: User,
    row: Notification,
    *,
    title: str | None = None,
    body: str | None = None,
    ttl: int | None = None,
) -> bool:
    """Remind the user of an EXISTING record. Returns whether any device was reached.

    The counterpart to `raise_notification` for a situation that persists: an overdue task
    buzzes every couple of hours, and each buzz is a delivery of the same record rather than a
    new record. Writing a record per buzz would put a column of near-identical rows in the
    panel each day and bury the notifications that are not about tasks.

    Subject to exactly the same suppression as a first delivery — quiet hours do not stop
    applying because the user has been told once already.

    `title` and `body` REPLACE the record's wording when given. That is not the same thing as
    rewriting history: the tag pins which situation this is, and the wording is a description
    of that situation as it reads now. Without this, renaming an overdue task would leave the
    reminder repeating the name it had when the record was first written.

    `created_at` is deliberately NOT touched. It says when the situation began, which is the
    useful fact ("overdue since 10:03"), and moving it would destroy that to gain nothing.
    """
    if title is not None and title != row.title:
        row.title = title
    if body is not None and body != row.body:
        row.body = body
    if db.is_modified(row):
        db.commit()

    spec = NotificationSpec(kind=row.kind, title=row.title, body=row.body, url=row.url, tag=row.tag)
    reason = _suppression_reason(db, user, spec, force_push=False)
    if reason is not None:
        log.info("reminder %s not pushed: %s", row.kind, reason)
        return False

    if not deliver(db, user, spec, ttl=ttl):
        return False
    _record_delivery(db, row)
    return True


def _record_delivery(db: Session, row: Notification) -> None:
    """One place where a successful delivery is written down, so the timestamp and the
    counter can never disagree about whether it happened."""
    row.pushed_at = dt.datetime.now(dt.UTC)
    row.push_count = (row.push_count or 0) + 1
    db.commit()


def todays_record(db: Session, user_id: uuid.UUID, kind: str, tag: str) -> Notification | None:
    """The live record raised for this exact situation today, if there is one.

    Two bounds, and each is doing work:

    **Live** (`deleted_at IS NULL`) — if the user removed today's reminder while the
    situation persists, the next check writes a fresh record rather than re-delivering a row
    that is not in the panel. Removing therefore does not silence the reminder, and does not
    resurrect what was removed either.

    **Today** (created since local midnight) — the panel is ordered `created_at DESC`. Without
    this, a task overdue for three weeks would hold a three-week-old record at the bottom of a
    fifty-row list while the phone buzzed about it every two hours: invisible in the very
    application doing the nudging. Bounding to a day also keeps the delivery count exact,
    because every delivery of a record created inside the 09:00-21:00 window falls on that
    record's own calendar day.
    """
    midnight = dt.datetime.now(_tz()).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.execute(
            select(Notification)
            .where(
                *_live(user_id),
                Notification.kind == kind,
                Notification.tag == tag,
                Notification.created_at >= midnight,
            )
            .order_by(Notification.created_at.desc())
        )
        .scalars()
        .first()
    )


def _suppression_reason(
    db: Session, user: User, spec: NotificationSpec, *, force_push: bool
) -> str | None:
    if force_push:
        return None
    if not push.configured():
        return "push is not configured on this server"
    if in_quiet_hours(user):
        return "quiet hours"
    cap = _cap(user)
    if cap and pushed_today(db, user.id) >= cap:
        return f"daily push cap of {cap} reached"
    return None


# The longest TTL a push service will accept — four weeks, FCM's documented maximum. Used
# for work that declared `catch_up=None`, meaning "however late", where there is no staleness
# at which delivering becomes worse than not delivering.
MAX_TTL_S = 2_419_200


def ttl_for(catch_up: dt.timedelta | None) -> int:
    """How long a push service should hold a notification, derived from the staleness bound
    of the work that raised it.

    **One declaration, both decisions.** A job's `catch_up` already says how late its output
    may be produced and still be worth producing. How long the push service should keep
    trying to deliver that output is the same question asked one step further along, so it is
    answered by the same number rather than by a second one that can drift.

    It did drift. `day_end_summary` declares `catch_up=3h` — "by midnight, so it still lands
    on the day it describes" — and was sent with `TTL: 86400`, instructing the push service to
    hold for a full day the thing the runner would have refused to produce after three hours.
    `morning_brief` said "delivered by 11:30 or not at all" and did the same.

    `None` means the work declared no bound, so neither does its delivery.
    """
    if catch_up is None:
        return MAX_TTL_S
    # A TTL of 0 is legal and means "deliver this instant or discard it", which is not what
    # any positive catch_up intends. The registry already refuses a non-positive catch_up;
    # this is the floor for the sub-second case it would still allow.
    return max(1, int(catch_up.total_seconds()))


def deliver(db: Session, user: User, spec: NotificationSpec, *, ttl: int | None = None) -> bool:
    """Push to every registered device. Returns whether any delivery succeeded.

    A dead subscription is DELETED rather than retried — a push service returns 404/410 once
    a browser has been uninstalled or its storage cleared, and keeping those is how a
    notification system quietly gets slower every month.
    """
    subs = (
        db.execute(select(PushSubscription).where(PushSubscription.user_id == user.id))
        .scalars()
        .all()
    )
    if not subs:
        return False

    payload = {"title": spec.title, "body": spec.body, "url": spec.url, "tag": spec.tag}
    if ttl is None:
        ttl = settings.push_ttl_default_s
    now = dt.datetime.now(dt.UTC)
    delivered = False

    for sub in subs:
        target = push.Subscription(endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth)
        try:
            push.send(target, payload, ttl=ttl, urgency=URGENCY)
        except push.PushGone:
            log.info("push subscription gone; removing it")
            db.delete(sub)
            continue
        except push.PushFailed as exc:
            sub.last_error_at = now
            sub.last_error = str(exc)[:200]
            continue
        except Exception as exc:  # noqa: BLE001 - delivery must never escape
            log.warning("push failed unexpectedly", exc_info=True)
            sub.last_error_at = now
            sub.last_error = type(exc).__name__
            continue
        sub.last_ok_at = now
        sub.last_error = None
        delivered = True

    db.commit()
    return delivered


# --- reading ------------------------------------------------------------------------


def _live(user_id: uuid.UUID):
    """The filter every reader that LISTS notifications applies.

    Bound to a name rather than repeated, so that the two readers which deliberately do NOT
    apply it — `pushed_today` and `already_said` — stand out as exceptions rather than
    looking like places somebody forgot.
    """
    return (Notification.user_id == user_id, Notification.deleted_at.is_(None))


def list_for_user(db: Session, user_id: uuid.UUID, limit: int = 50) -> list[Notification]:
    return list(
        db.execute(
            select(Notification)
            .where(*_live(user_id))
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.execute(
            select(func.count())
            .select_from(Notification)
            .where(*_live(user_id), Notification.read_at.is_(None))
        ).scalar_one()
        or 0
    )


def _get(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification | None:
    """Fetch a LIVE notification. A deleted one is indistinguishable from one that never
    existed, which is what makes 404 the honest answer to both."""
    return db.execute(
        select(Notification).where(*_live(user_id), Notification.id == notification_id)
    ).scalar_one_or_none()


def mark_read(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification | None:
    row = _get(db, user_id, notification_id)
    if row is None:
        return None
    if row.read_at is None:
        row.read_at = dt.datetime.now(dt.UTC)
        db.commit()
    return row


def mark_all_read(db: Session, user_id: uuid.UUID) -> int:
    rows = (
        db.execute(select(Notification).where(*_live(user_id), Notification.read_at.is_(None)))
        .scalars()
        .all()
    )
    now = dt.datetime.now(dt.UTC)
    for row in rows:
        row.read_at = now
    db.commit()
    return len(rows)


def already_said(
    db: Session, user_id, kind: str, tag: str, since: dt.timedelta | None = None
) -> bool:
    """Whether this exact thing has already been raised.

    ⚠ **Only for subjects reported on CROSSING** — `disk_watch` and `budget_watch`, which
    report a continuous measurement entering a worse band. `task_nudge` no longer calls this,
    and the reason it stopped is the most expensive thing this module has learned.

    The `tag` carries the state being reported. Same tag means the situation has not changed,
    so saying it again would be repetition rather than news.

    **That is true of a measurement and false of a set.** The overdue-task tag was a hash of
    which task ids were overdue, and this docstring used to argue that such a tag "stops
    matching by itself the moment the situation changes, so an unbounded lookback is exactly
    right". It samples the state; it cannot represent a transition. `{gifts}` -> `{}` ->
    `{gifts}` produces the identical tag at both ends, so the second episode was suppressed by
    a notification from the first.

    In production that ran as follows: the nudge raised one notification ever, on 2026-08-24,
    which was never delivered (no device had subscribed yet) and was then removed from the
    panel. The task was rescheduled, went overdue again two days later, matched the same tag,
    and the job returned `already_told` on every run afterwards. The feature was silent from
    its first firing and nothing anywhere reported an error.

    A band cannot do this, because a measurement that leaves a band and returns has genuinely
    changed twice and the `since` bound below covers the return. A set can, which is why the
    overdue nudge now reminds until the user acts rather than asking this question at all.

    ⚠ **Deliberately does not filter `deleted_at`** (migration 012 made notifications
    deletable). This asks what has already been SAID, not what is still on screen. Filter
    deleted rows here and dismissing "3 tasks are overdue" would erase the evidence that it
    was ever said, so the next hourly run would treat it as news and push it again — delete
    would silently acquire the meaning "remind me within the hour", on precisely the
    notification most likely to be dismissed.

    `since` bounds how far back the lookback reaches, and whether you need one depends on
    whether the tag can repeat itself:

    - **A tag containing a date or month cannot.** `journal-2026-08-27` and
      `budget-warn-2026-08` are each reachable on exactly one day or in one month, so an
      unbounded lookback is safe and a bound would be noise.
    - **A tag naming a state can.** `disk-80` is reachable again every time usage drifts back
      up, so without `since` crossing 80% would be reported once in the lifetime of the
      installation: clear some space, drift up a month later, and the ancient row silences it
      forever.

    The test is whether the tag contains something monotonic. If it does not, pass `since`.
    The overdue fingerprint contained nothing monotonic and no bound, which is the failure
    described above.

    Getting this wrong produces either an alert that never fires again or one that fires every
    run, and both look exactly like the code working.
    """
    stmt = select(Notification.id).where(
        Notification.user_id == user_id,
        Notification.kind == kind,
        Notification.tag == tag,
    )
    if since is not None:
        stmt = stmt.where(Notification.created_at >= dt.datetime.now(dt.UTC) - since)
    return db.execute(stmt.limit(1)).first() is not None


# --- removal ------------------------------------------------------------------------
#
# Soft, and reversible for the length of an undo toast — the same treatment tasks, journal
# entries and conversations have had since migration 004.
#
# What removal does NOT do is rewrite history. See `pushed_today` and `already_said`.


def delete_notification(
    db: Session, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification | None:
    row = _get(db, user_id, notification_id)
    if row is None:
        return None
    row.deleted_at = dt.datetime.now(dt.UTC)
    db.commit()
    return row


def restore_notification(
    db: Session, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification | None:
    """Undo. Deliberately does not use `_get`, which only sees live rows."""
    row = db.execute(
        select(Notification).where(
            Notification.user_id == user_id, Notification.id == notification_id
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.deleted_at = None
    db.commit()
    return row


def clear_read(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Remove everything already read, and return exactly which ids were removed.

    Returning the ids is what makes undo correct rather than approximately correct. "Restore
    everything read" would be the obvious inverse and is wrong: anything marked read between
    the clear and the undo would be restored along with it, resurrecting rows the user never
    deleted.
    """
    rows = (
        db.execute(select(Notification).where(*_live(user_id), Notification.read_at.is_not(None)))
        .scalars()
        .all()
    )
    now = dt.datetime.now(dt.UTC)
    for row in rows:
        row.deleted_at = now
    db.commit()
    return [row.id for row in rows]


def restore_notifications(db: Session, user_id: uuid.UUID, ids: list[uuid.UUID]) -> int:
    if not ids:
        return 0
    rows = (
        db.execute(
            select(Notification).where(Notification.user_id == user_id, Notification.id.in_(ids))
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.deleted_at = None
    db.commit()
    return len(rows)


# --- subscriptions ------------------------------------------------------------------


def subscribe(
    db: Session, user_id: uuid.UUID, endpoint: str, p256dh: str, auth: str, user_agent: str | None
) -> PushSubscription:
    """Register or refresh a browser. Keyed on `endpoint` so re-subscribing the same
    browser updates its keys instead of accumulating a second row that will never work."""
    existing = db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    ).scalar_one_or_none()
    if existing is not None:
        existing.user_id = user_id
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = user_agent
        existing.last_error = None
        existing.last_error_at = None
        db.commit()
        return existing
    row = PushSubscription(
        id=uuid.uuid4(),
        user_id=user_id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=user_agent,
    )
    db.add(row)
    db.commit()
    return row


def unsubscribe(db: Session, user_id: uuid.UUID, endpoint: str) -> bool:
    result = db.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint
        )
    )
    db.commit()
    return bool(result.rowcount)


def subscription_count(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.execute(
            select(func.count())
            .select_from(PushSubscription)
            .where(PushSubscription.user_id == user_id)
        ).scalar_one()
        or 0
    )
