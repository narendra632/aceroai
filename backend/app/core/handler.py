"""The one brain. Every conversational message, from any channel, flows through
`handle_message`. Routes and channel adapters are pure transport (golden rule 1).

The route is async (it streams); the DB is sync. So DB work happens only before
the stream (persist the user turn) and after it (persist the assistant turn),
each wrapped in `run_in_threadpool` — the event loop is never blocked, and the
DB is never touched mid-stream.
"""

import uuid
from collections.abc import AsyncIterator

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core import composer, llm
from app.db.models import ChatSession, Message, User

TITLE_MAX = 60


def _title_from(text: str) -> str:
    title = " ".join(text.split())
    return title[:TITLE_MAX] if title else "New chat"


def _persist_user_turn(
    db: Session, user: User, text: str, channel: str, session_id: uuid.UUID | None
) -> uuid.UUID:
    if session_id is not None:
        session = db.get(ChatSession, session_id)
        if session is None or session.user_id != user.id:
            raise ValueError("session not found")
    else:
        session = ChatSession(user_id=user.id, channel=channel, title=_title_from(text))
        db.add(session)
        db.flush()
    db.add(Message(session_id=session.id, role="user", content=text))
    session.last_active_at = func.now()
    db.commit()
    return session.id


def _persist_assistant_turn(
    db: Session, session_id: uuid.UUID, content: str, model: str, usage: dict
) -> uuid.UUID:
    msg = Message(
        session_id=session_id,
        role="assistant",
        content=content,
        model=model,
        tokens_in=usage.get("tokens_in"),
        tokens_out=usage.get("tokens_out"),
    )
    db.add(msg)
    session = db.get(ChatSession, session_id)
    if session is not None:
        session.last_active_at = func.now()
    db.commit()
    return msg.id


async def handle_message(
    db: Session,
    user: User,
    text: str,
    channel: str,
    session_id: uuid.UUID | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Yield (event, data) pairs: one `session`, many `delta`, then `done`
    (or a single `error`). The transport layer decides how to render them."""
    session_id = await run_in_threadpool(_persist_user_turn, db, user, text, channel, session_id)
    yield "session", str(session_id)

    context = await run_in_threadpool(composer.build_context, db, session_id)

    usage: dict = {}
    parts: list[str] = []
    try:
        async for delta in llm.stream_chat(context, usage=usage):
            parts.append(delta)
            yield "delta", delta
    except Exception as exc:  # noqa: BLE001 - surface any provider error to the client
        yield "error", str(exc)
        return

    message_id = await run_in_threadpool(
        _persist_assistant_turn, db, session_id, "".join(parts), settings.model_chat, usage
    )
    yield "done", str(message_id)
