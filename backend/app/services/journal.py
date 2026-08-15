"""Journal service: add/read/update/delete dated entries, always user-scoped.

An entry records its `entry_date`, free-text `content`, optional `mood` (1-5),
`tags`, and the `channel` it came from (web / telegram / assistant). Multiple
entries per day are allowed.
"""

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JournalEntry
from app.services.errors import Invalid, NotFound

LIST_LIMIT = 100


def _today() -> dt.date:
    # "Today" in the user's timezone, so a late-night entry lands on the right day.
    return dt.datetime.now(ZoneInfo(settings.app_timezone)).date()


def _validate_mood(mood: int | None) -> None:
    if mood is not None and not (1 <= mood <= 5):
        raise Invalid("mood must be between 1 and 5")


def get_entry(db: Session, user_id: uuid.UUID, entry_id: uuid.UUID) -> JournalEntry:
    entry = db.get(JournalEntry, entry_id)
    if entry is None or entry.user_id != user_id:
        raise NotFound("journal entry not found")
    return entry


def list_entries(
    db: Session,
    user_id: uuid.UUID,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int = LIST_LIMIT,
) -> list[JournalEntry]:
    """The user's entries, most recent first, optionally within an entry-date range."""
    stmt = select(JournalEntry).where(JournalEntry.user_id == user_id)
    if start is not None:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end is not None:
        stmt = stmt.where(JournalEntry.entry_date <= end)
    stmt = stmt.order_by(JournalEntry.created_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def add_entry(
    db: Session,
    user_id: uuid.UUID,
    content: str,
    mood: int | None = None,
    tags: list[str] | None = None,
    channel: str = "web",
    entry_date: dt.date | None = None,
) -> JournalEntry:
    content = (content or "").strip()
    if not content:
        raise Invalid("a journal entry needs content")
    _validate_mood(mood)
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date or _today(),
        content=content,
        mood=mood,
        tags=tags or [],
        channel=channel,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def update_entry(
    db: Session,
    user_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    content: str | None = None,
    mood: int | None = None,
    tags: list[str] | None = None,
) -> JournalEntry:
    entry = get_entry(db, user_id, entry_id)
    if content is not None:
        content = content.strip()
        if not content:
            raise Invalid("a journal entry needs content")
        entry.content = content
    if mood is not None:
        _validate_mood(mood)
        entry.mood = mood
    if tags is not None:
        entry.tags = tags
    db.commit()
    db.refresh(entry)
    return entry


def delete_entry(db: Session, user_id: uuid.UUID, entry_id: uuid.UUID) -> None:
    entry = get_entry(db, user_id, entry_id)
    db.delete(entry)
    db.commit()
