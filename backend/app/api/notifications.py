"""Reading what Acero has said, and registering a device to be told on.

Every route is scoped to the authenticated user. That is not boilerplate here: a push
subscription is a capability to interrupt someone, so an endpoint that could be registered
against another account, or read from one, would be a real hole rather than an untidiness.

The one credential involved — the VAPID private key — never appears in any response. The
*public* key does, because the browser needs it to subscribe and it is public by design.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import (
    NotificationList,
    NotificationOut,
    PushStatusOut,
    PushSubscribeIn,
)
from app.config import settings
from app.core import push
from app.db.models import User
from app.db.session import get_db
from app.jobs.registry import Notification as NotificationSpec
from app.services import notifications

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
def list_notifications(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationList:
    rows = notifications.list_for_user(db, user.id, limit=min(limit, 200))
    return NotificationList(
        items=[NotificationOut.model_validate(r) for r in rows],
        unread=notifications.unread_count(db, user.id),
    )


@router.get("/unread", response_model=dict)
def unread(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Polled by the bell, so kept as cheap as possible — one indexed count, no rows."""
    return {"unread": notifications.unread_count(db, user.id)}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationOut:
    row = notifications.mark_read(db, user.id, notification_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return NotificationOut.model_validate(row)


@router.post("/read-all", response_model=dict)
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {"marked": notifications.mark_all_read(db, user.id)}


# --- push subscriptions ---------------------------------------------------------------


@router.get("/push", response_model=PushStatusOut)
def push_status(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PushStatusOut:
    return PushStatusOut(
        configured=push.configured(),
        public_key=settings.vapid_public_key,
        devices=notifications.subscription_count(db, user.id),
        quiet_hours_start=user.quiet_hours_start,
        quiet_hours_end=user.quiet_hours_end,
        daily_push_cap=user.daily_push_cap,
    )


@router.post("/push", response_model=dict, status_code=status.HTTP_201_CREATED)
def subscribe(
    body: PushSubscribeIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    notifications.subscribe(
        db,
        user.id,
        endpoint=body.endpoint,
        p256dh=body.p256dh,
        auth=body.auth,
        # Only so two devices are distinguishable in Settings. Truncated because a UA
        # string is attacker-controlled text and there is no reason to store all of it.
        user_agent=(request.headers.get("User-Agent") or "")[:200] or None,
    )
    return {"ok": True, "devices": notifications.subscription_count(db, user.id)}


@router.delete("/push", response_model=dict)
def unsubscribe(
    endpoint: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    removed = notifications.unsubscribe(db, user.id, endpoint)
    return {"ok": removed, "devices": notifications.subscription_count(db, user.id)}


@router.post("/push/test", response_model=dict)
def send_test(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Send a notification on demand.

    This exists because push involves five parties and four of them are somebody else's.
    Without a way to provoke one deliberately, "nothing arrived" is indistinguishable from
    a wrong key, a refused permission, a service worker that never registered, a quiet-hours
    suppression, and a device with no network — and finding out which takes an evening.

    Bypasses quiet hours and the daily cap on purpose: the user asked for this one, so
    policy meant to prevent unrequested interruptions does not apply.
    """
    if not push.configured():
        return {"ok": False, "reason": "This server has no VAPID keys configured."}
    if notifications.subscription_count(db, user.id) == 0:
        return {"ok": False, "reason": "No device is subscribed yet."}

    spec = NotificationSpec(
        kind="test",
        title="Acero is set up",
        body="Notifications will arrive here.",
        url="/#settings",
        tag="test",
    )
    row = notifications.raise_notification(db, user, spec, force_push=True)
    if row.pushed_at is None:
        return {"ok": False, "reason": "The push was recorded but no device accepted it."}
    return {"ok": True}
