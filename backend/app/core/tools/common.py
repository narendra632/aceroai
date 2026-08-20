"""Argument parsing shared by every tool module.

These raise `Invalid`, which `execute` turns into `{"ok": False, "error": ...}` — so a model
that passes `"next tuesday"` where an ISO date belongs gets told what was wrong and can try
again, instead of the turn failing.
"""

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.errors import Invalid


def parse_dt(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise Invalid(f"'{value}' is not a valid ISO 8601 date/time") from exc
    if parsed.tzinfo is None:  # assume the user's timezone when none is given
        parsed = parsed.replace(tzinfo=ZoneInfo(settings.app_timezone))
    return parsed


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise Invalid(f"'{value}' is not a valid ISO date (YYYY-MM-DD)") from exc


def parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise Invalid(f"'{value}' is not a valid id") from exc
