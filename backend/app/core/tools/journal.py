"""Journal tools: recording and reading what the user wrote about their days."""

import uuid

from sqlalchemy.orm import Session

from app.core.tools.common import parse_date
from app.db.models import JournalEntry
from app.services import journal as journal_svc

SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "add_journal_entry",
            "description": "Record a journal entry for the user (what happened / how they feel).",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The entry text."},
                    "mood": {"type": "integer", "enum": [1, 2, 3, 4, 5], "description": "1-5."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_journal",
            "description": "List recent journal entries (optionally within a date range).",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "ISO date (YYYY-MM-DD)."},
                    "end": {"type": "string", "description": "ISO date (YYYY-MM-DD)."},
                },
            },
        },
    },
]


def summary(e: JournalEntry) -> dict:
    return {
        "id": str(e.id),
        "entry_date": e.entry_date.isoformat(),
        "content": e.content,
        "mood": e.mood,
        "tags": list(e.tags or []),
    }


def _add_journal_entry(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    entry = journal_svc.add_entry(
        db,
        user_id,
        content=a.get("content", ""),
        mood=int(a["mood"]) if a.get("mood") is not None else None,
        tags=a.get("tags"),
        channel="assistant",
    )
    return summary(entry)


def _list_journal(db: Session, user_id: uuid.UUID, a: dict) -> list[dict]:
    rows = journal_svc.list_entries(
        db,
        user_id,
        start=parse_date(a["start"]) if a.get("start") else None,
        end=parse_date(a["end"]) if a.get("end") else None,
    )
    return [summary(e) for e in rows]


HANDLERS = {
    "add_journal_entry": _add_journal_entry,
    "list_journal": _list_journal,
}
