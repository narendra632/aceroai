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

# Notification kinds that are worth waiting a day for if the device is offline. Everything
# else is time-sensitive enough that a stale delivery is worse than none.
_DIGEST_KINDS = frozenset({"morning_brief", "day_end_summary", "weekly_review"})


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

    Public rather than underscored because Settings now displays it.
    """
    midnight = dt.datetime.now(_tz()).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.pushed_at.is_not(None),
                Notification.pushed_at >= midnight,
            )
        ).scalar_one()
        or 0
    )


def _cap(user: User) -> int:
    """The ceiling on deliveries per day. **Zero means no ceiling, and is the default.**

    The ceiling used to default to 6 while `task_nudge` alone can fire thirteen times a day,
    so it was binding in ordinary use — which means it was silently discarding notifications
    the user wanted, starting with the most frequent ones. A limit reached during normal
    operation is not a safety limit; it is an undocumented feature that stops telling you
    things after lunch.

    Volume is governed by whether something is *news* — the per-tag suppression in
    `jobs/nudges.py` — which is the right control for expected volume.

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
    force_push: bool = False,
) -> Notification:
    """Record a notification and try to deliver it. Returns the stored row.

    Never raises. A notification that cannot be delivered is still a notification that
    happened, and the caller — usually a job — must not be failed by a phone.
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

    delivered = deliver(db, user, spec)
    if delivered:
        row.pushed_at = dt.datetime.now(dt.UTC)
        db.commit()
    return row


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


def _ttl_for(kind: str) -> int:
    return settings.push_ttl_digest_s if kind in _DIGEST_KINDS else settings.push_ttl_nudge_s


def deliver(db: Session, user: User, spec: NotificationSpec) -> bool:
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
    ttl = _ttl_for(spec.kind)
    urgency = "low" if spec.kind in _DIGEST_KINDS else "normal"
    now = dt.datetime.now(dt.UTC)
    delivered = False

    for sub in subs:
        target = push.Subscription(endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth)
        try:
            push.send(target, payload, ttl=ttl, urgency=urgency)
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

    The `tag` carries the state being reported — for overdue tasks, a hash of which tasks
    they are. Same tag means the situation has not changed, so saying it again would be
    repetition rather than news.

    ⚠ **Deliberately does not filter `deleted_at`** (migration 012 made notifications
    deletable). This asks what has already been SAID, not what is still on screen. Filter
    deleted rows here and dismissing "3 tasks are overdue" would erase the evidence that it
    was ever said, so the next hourly run would treat it as news and push it again — delete
    would silently acquire the meaning "remind me within the hour", on precisely the
    notification most likely to be dismissed.

    `since` bounds how far back the lookback reaches, and which behaviour is correct depends
    entirely on the shape of the tag:

    - A tag that encodes a CHANGING SET — the overdue-task fingerprint — wants no bound. It
      stops matching by itself the moment the situation changes, so an unbounded lookback is
      exactly right and a bounded one would re-announce an unchanged situation.
    - A tag that can RECUR — a disk-usage band — needs one. Without it, crossing 80% once
      would be reported once in the lifetime of the installation: clear some space, drift
      back up a month later, and the ancient row silences it forever.

    Getting this backwards produces either an alert that never fires again or one that fires
    every run, and both look like the code working.
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
