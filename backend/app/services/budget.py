"""A monthly spend ceiling.

Observability could report cost but never stop it: a runaway loop was visible on the
Insights page *afterwards*, not prevented. This is the missing half.

Three deliberate choices:

  * **Checked before each message, not enforced mid-turn.** A turn already in flight
    finishes and can carry the total slightly past the limit. Killing a reply halfway
    through to save a fraction of a cent would be a worse product than overshooting by
    one message, and the user is told this rather than left to discover it.
  * **Everything counts** — replies, recall embeddings and fact extraction — because
    that is what the provider actually bills. Counting only visible replies would let a
    third of the calls escape the ceiling entirely.
  * **The month is a calendar month in the user's timezone**, so "resets on the 1st"
    means their 1st, and it lines up with the day buckets the Insights page draws.

NULL limit means no limit. An account that never sets one behaves exactly as before.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.services import insights

# Where "you are approaching the limit" begins. Being cut off with no warning is a bad
# experience; a warning band is what makes the stop predictable rather than sudden.
WARN_RATIO = 0.8


class BudgetExceeded(Exception):
    """Raised when a turn would run past the user's monthly ceiling."""


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def month_start(now: dt.datetime | None = None) -> dt.datetime:
    """First instant of the current calendar month, in the user's timezone, as UTC."""
    local = (now or dt.datetime.now(dt.UTC)).astimezone(_tz())
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(dt.UTC)


def next_month_start(now: dt.datetime | None = None) -> dt.date:
    """The day the allowance resets — shown so the stop has a visible end."""
    start = month_start(now).astimezone(_tz()).date()
    return (start.replace(day=28) + dt.timedelta(days=7)).replace(day=1)


def status(db: Session, user: User) -> dict:
    """Everything the interface needs to explain the state in one glance."""
    limit = user.monthly_budget_usd
    spent = insights.spend_since(db, user.id, month_start())

    if limit is None or limit <= 0:
        state = "off"
        ratio = 0.0
        remaining = None
    else:
        ratio = float(spent / limit)
        remaining = max(Decimal(0), limit - spent)
        if spent >= limit:
            state = "exceeded"
        elif ratio >= WARN_RATIO:
            state = "warning"
        else:
            state = "ok"

    return {
        "limit_usd": limit,
        "spent_usd": spent,
        "remaining_usd": remaining,
        "used_ratio": ratio,
        "state": state,
        "resets_on": next_month_start(),
        "warn_ratio": WARN_RATIO,
    }


def check(db: Session, user: User) -> None:
    """Raise if this user has already spent their month's allowance.

    Called at the top of the one brain, so every channel is covered by one check and no
    channel can forget it.
    """
    limit = user.monthly_budget_usd
    if limit is None or limit <= 0:
        return
    spent = insights.spend_since(db, user.id, month_start())
    if spent >= limit:
        raise BudgetExceeded(message(spent, limit))


def message(spent: Decimal, limit: Decimal) -> str:
    """What the user reads. Says what happened, what it costs them, and how to undo it —
    a refusal that does not tell you how to proceed is just a wall."""
    # Day formatted by hand: "%-d" is glibc-only and "%#d" is Windows-only, so either
    # crashes on the other platform. This project is developed on Windows and runs on Linux.
    resets = next_month_start()
    return (
        f"You've reached your monthly spend limit of ${limit:.2f} "
        f"(${spent:.2f} used). Replies are paused until "
        f"{resets.day} {resets:%B}, or raise the limit in Settings."
    )
