"""Builds the model's input for a session: the SOUL.md persona as the system
message, followed by the session's recent messages in chronological order.

Later features extend this one function (profile facts, tasks); routes and
channels never change. This is where "what the model sees" is decided.
"""

import datetime as dt
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Message

# backend/app/core/composer.py -> parents[3] is the repo root.
_DEFAULT_SOUL_PATH = Path(__file__).resolve().parents[3] / "docs" / "SOUL.md"
HISTORY_LIMIT = 20

_FALLBACK_PERSONA = "You are Acero, a concise, warm personal assistant."


def _persona_path() -> Path:
    # In prod the image has no docs/, so the deploy sets SOUL_PATH to a mounted copy.
    return Path(settings.soul_path) if settings.soul_path else _DEFAULT_SOUL_PATH


def _read_persona() -> str:
    try:
        return _persona_path().read_text(encoding="utf-8").strip()
    except OSError:
        # last-resort fallback so chat never breaks on a missing persona file.
        return _FALLBACK_PERSONA


def _now_block() -> str:
    # Give the model the current date/time so it can resolve relative dates like
    # "Friday" or "tomorrow" when creating tasks.
    now = dt.datetime.now(ZoneInfo(settings.app_timezone))
    return f"Current date and time: {now:%A %Y-%m-%d %H:%M} ({settings.app_timezone})."


def _facts_block(facts: list[str]) -> str:
    lines = "\n".join(f"- {f}" for f in facts)
    return (
        "What you know about the user, recalled from earlier conversations "
        f"(most relevant first):\n{lines}"
    )


def build_context(db: Session, session_id: uuid.UUID, facts: list[str] | None = None) -> list[dict]:
    """Assemble model input: SOUL.md persona, then the semantically-recalled
    profile facts (when any), then the session's recent messages in order.

    `facts` are recalled by the handler (an async embedding step) and passed in,
    so this stays a pure, synchronous DB read.
    """
    rows = (
        db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_LIMIT)
        )
        .scalars()
        .all()
    )
    context: list[dict] = [
        {"role": "system", "content": _read_persona()},
        {"role": "system", "content": _now_block()},
    ]
    if facts:
        context.append({"role": "system", "content": _facts_block(facts)})
    for m in reversed(rows):
        if m.role in ("user", "assistant"):
            context.append({"role": m.role, "content": m.content})
    return context
