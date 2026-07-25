"""Builds the model's input for a session: the SOUL.md persona as the system
message, followed by the session's recent messages in chronological order.

Later features extend this one function (profile facts, tasks); routes and
channels never change. This is where "what the model sees" is decided.
"""

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Message

# backend/app/core/composer.py -> parents[3] is the repo root.
SOUL_PATH = Path(__file__).resolve().parents[3] / "docs" / "SOUL.md"
HISTORY_LIMIT = 20

_FALLBACK_PERSONA = "You are Acero, a concise, warm personal assistant."


def _read_persona() -> str:
    try:
        return SOUL_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        # docs/ is not copied into the production image; fall back gracefully.
        return _FALLBACK_PERSONA


def build_context(db: Session, session_id: uuid.UUID) -> list[dict]:
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
    context: list[dict] = [{"role": "system", "content": _read_persona()}]
    for m in reversed(rows):
        if m.role in ("user", "assistant"):
            context.append({"role": m.role, "content": m.content})
    return context
