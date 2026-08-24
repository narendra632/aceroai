"""Journal service: add/read/update/delete dated entries, always user-scoped.

An entry records its `entry_date`, free-text `content`, optional `mood` (1-5),
`tags`, and the `channel` it came from (web / assistant). Multiple
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


def get_entry(
    db: Session, user_id: uuid.UUID, entry_id: uuid.UUID, *, include_deleted: bool = False
) -> JournalEntry:
    """Fetch one owned entry. `include_deleted` is only for restore — to every other
    caller a deleted entry must look exactly like one that never existed."""
    entry = db.get(JournalEntry, entry_id)
    if entry is None or entry.user_id != user_id:
        raise NotFound("journal entry not found")
    if entry.deleted_at is not None and not include_deleted:
        raise NotFound("journal entry not found")
    return entry


def list_entries(
    db: Session,
    user_id: uuid.UUID,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int = LIST_LIMIT,
    offset: int = 0,
    q: str | None = None,
) -> list[JournalEntry]:
    """The user's live entries, most recent first.

    Optionally narrowed by entry-date range and by `q`, a case-insensitive **substring**
    match on the content.

    `ILIKE` rather than full-text search, deliberately — but the reason is cost, not
    equivalence. Substring matching is genuinely worse at matching: "ran" also finds
    "errands", and "running" does *not* find "I ran 5k" (no stemming). Full-text
    (`tsvector` + GIN) would fix both, at the price of a generated column, an index, a
    migration, and a language configuration that suits mixed-language entries.

    It is not taken because the better end-state is **semantic** search over the
    embeddings this app already produces — which finds "times I felt burnt out" in an
    entry that never uses those words. That is on the roadmap; spending a migration on
    `tsvector` first would be paying for a stepping stone we intend to step over.
    """
    stmt = select(JournalEntry).where(
        JournalEntry.user_id == user_id, JournalEntry.deleted_at.is_(None)
    )
    if start is not None:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end is not None:
        stmt = stmt.where(JournalEntry.entry_date <= end)
    if q:
        term = q.strip()
        if term:
            # escape LIKE wildcards so a literal % or _ searches for itself
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(JournalEntry.content.ilike(f"%{escaped}%", escape="\\"))
    stmt = stmt.order_by(JournalEntry.created_at.desc()).limit(limit).offset(offset)
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
    """Soft delete, so the deletion can be undone. The row stays; every reader filters
    it out via `list_entries` / `get_entry`."""
    entry = get_entry(db, user_id, entry_id)
    entry.deleted_at = dt.datetime.now(dt.UTC)
    db.commit()


def restore_entry(db: Session, user_id: uuid.UUID, entry_id: uuid.UUID) -> JournalEntry:
    """Undo a delete. Restoring an entry that is already live is a no-op rather than an
    error, so a double-tap on Undo cannot fail."""
    entry = get_entry(db, user_id, entry_id, include_deleted=True)
    entry.deleted_at = None
    db.commit()
    db.refresh(entry)
    return entry
