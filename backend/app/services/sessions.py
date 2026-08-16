"""Chat session service: list, read, rename, delete and restore conversations.

This layer exists for the same reason `tasks.py` and `journal.py` do — it is the single
place session data is queried, so the soft-delete filter has exactly one home and every
caller inherits it. Until this module existed, `api/chat.py` queried `ChatSession` and
`Message` directly in its routes, which would have left that filter in two places.

Deleting a conversation soft-deletes the session and **keeps its messages**, so an undo
restores the conversation intact. Learned profile facts are deliberately never touched:
memory about the user outlives any single conversation.
"""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatSession, Message
from app.services.errors import Invalid, NotFound

TITLE_MAX = 200


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _live(stmt):
    """Restrict a ChatSession query to rows the user has not deleted."""
    return stmt.where(ChatSession.deleted_at.is_(None))


def get_session(
    db: Session,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    include_deleted: bool = False,
) -> ChatSession:
    """Fetch one owned session. `include_deleted` is only for restore — every other
    caller must see a deleted session exactly as it would see a non-existent one."""
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user_id:
        raise NotFound("session not found")
    if session.deleted_at is not None and not include_deleted:
        raise NotFound("session not found")
    return session


def list_sessions(db: Session, user_id: uuid.UUID) -> list[ChatSession]:
    """The user's live conversations, most recently active first."""
    stmt = _live(select(ChatSession).where(ChatSession.user_id == user_id))
    stmt = stmt.order_by(ChatSession.last_active_at.desc())
    return list(db.execute(stmt).scalars().all())


def list_messages(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> list[Message]:
    """A conversation's messages in order. Ownership is checked first, so this 404s for
    a session that is not the caller's — or that they have deleted."""
    get_session(db, user_id, session_id)
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
    return list(db.execute(stmt).scalars().all())


def rename_session(
    db: Session, user_id: uuid.UUID, session_id: uuid.UUID, title: str
) -> ChatSession:
    title = (title or "").strip()
    if not title:
        raise Invalid("a conversation needs a title")
    if len(title) > TITLE_MAX:
        raise Invalid(f"title must be {TITLE_MAX} characters or fewer")
    session = get_session(db, user_id, session_id)
    session.title = title
    db.commit()
    db.refresh(session)
    return session


def delete_session(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    """Soft delete. Messages are kept so a restore returns the whole conversation."""
    session = get_session(db, user_id, session_id)
    session.deleted_at = _now()
    db.commit()


def restore_session(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> ChatSession:
    """Undo a delete. Restoring an already-live session is a no-op, not an error, so a
    double-tap on Undo cannot fail."""
    session = get_session(db, user_id, session_id, include_deleted=True)
    session.deleted_at = None
    db.commit()
    db.refresh(session)
    return session


def drop_last_reply(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    """Remove the trailing assistant message so the turn can be regenerated.

    Only a *trailing* assistant message is removed — if the last message is the user's,
    there is nothing to regenerate and this is a no-op. Facts already extracted from the
    discarded reply are NOT retracted; see the note in docs/ARCHITECTURE.md.
    """
    get_session(db, user_id, session_id)
    last = db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if last is not None and last.role == "assistant":
        db.delete(last)
        db.commit()
