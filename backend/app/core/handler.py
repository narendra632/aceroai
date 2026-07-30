"""The one brain. Every conversational message, from any channel, flows through
`handle_message`. Routes and channel adapters are pure transport (golden rule 1).

The route is async (it streams); the DB is sync. So DB work happens only before
the stream (persist the user turn) and after it (persist the assistant turn),
each wrapped in `run_in_threadpool` — the event loop is never blocked, and the
DB is never touched mid-stream.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi.concurrency import run_in_threadpool
from openai import RateLimitError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core import composer, llm, memory
from app.db.models import ChatSession, Message, User

log = logging.getLogger(__name__)

TITLE_MAX = 60

# Hold references to background extraction tasks so they aren't garbage-collected
# before they finish (asyncio only keeps weak references to running tasks).
_bg_tasks: set[asyncio.Task] = set()


def _user_error(exc: Exception) -> str:
    """Map a provider exception to a safe, friendly message. Full detail is logged
    server-side; the raw provider text is never sent to the client."""
    if isinstance(exc, RateLimitError):
        return "I've hit the model's rate limit for now — please try again in a little while."
    return "Something went wrong reaching the model. Please try again."


def _schedule_extraction(user_id: uuid.UUID, user_text: str, reply_text: str) -> None:
    try:
        task = asyncio.create_task(memory.extract_and_store(user_id, user_text, reply_text))
    except RuntimeError:  # no running loop (shouldn't happen from the async handler)
        return
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


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
    reasoning_effort: str | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Yield (event, data) pairs: one `session`, many `delta`, then `done`
    (or a single `error`). The transport layer decides how to render them.

    `reasoning_effort` is the adaptive-reasoning hook: a caller (a channel acting
    on explicit user intent, or a future task like the daily review) may pass a
    specific effort; otherwise chat defaults to `settings.reasoning_effort_chat`.
    """
    effort = reasoning_effort if reasoning_effort is not None else settings.reasoning_effort_chat
    text = text or ""
    if len(text) > settings.max_input_chars:
        yield "error", f"That message is too long (max {settings.max_input_chars} characters)."
        return

    session_id = await run_in_threadpool(_persist_user_turn, db, user, text, channel, session_id)
    yield "session", str(session_id)

    # Semantic recall (best-effort): the most relevant facts about the user for
    # this message, injected into context. A failure here never blocks the reply.
    facts = await memory.recall(db, user, text)
    context = await run_in_threadpool(composer.build_context, db, session_id, facts)

    usage: dict = {}
    parts: list[str] = []
    try:
        async for delta in llm.stream_chat(context, usage=usage, reasoning_effort=effort):
            parts.append(delta)
            yield "delta", delta
    except Exception as exc:  # noqa: BLE001 - one place to catch any provider failure
        log.warning("generation failed for session %s", session_id, exc_info=True)
        yield "error", _user_error(exc)
        return

    reply = "".join(parts)
    message_id = await run_in_threadpool(
        _persist_assistant_turn, db, session_id, reply, settings.model_chat, usage
    )
    yield "done", str(message_id)

    # Learn durable facts from this turn, off the reply path.
    if settings.memory_extraction_enabled and reply:
        _schedule_extraction(user.id, text, reply)
