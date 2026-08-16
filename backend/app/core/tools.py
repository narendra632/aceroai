"""Assistant tools: the functions the model may call during a chat turn, plus a
dispatcher that executes a call against the user's data via the service layer.

Design guarantees (see the assistant-tools spec):
- **User-scoped by construction.** Every tool closes over the authenticated
  `user_id`; the model never supplies one. An id it passes is validated by the
  service to belong to that user, or the call fails.
- **Fault-tolerant.** `execute` never raises: a bad id, invalid input, or internal
  error comes back as `{"ok": False, "error": ...}` so the model can self-correct
  or explain, and the chat turn always completes.

Tools are thin wrappers over `app.services.*` — no business logic lives here, so the
assistant and the REST API stay identical.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Callable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JournalEntry, Task
from app.services import journal as journal_svc
from app.services import tasks as tasks_svc
from app.services.errors import Duplicate, Invalid, NotFound

log = logging.getLogger(__name__)


# --- OpenAI-style tool definitions handed to the model ---------------------------

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": (
                "Add a to-do task for the user. Use when the user clearly wants to "
                "remember to do something."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short task title."},
                    "notes": {"type": "string", "description": "Optional extra detail."},
                    "priority": {
                        "type": "integer",
                        "enum": [1, 2, 3],
                        "description": "1 high, 2 medium, 3 low. Default 2.",
                    },
                    "due_at": {
                        "type": "string",
                        "description": "Optional due date/time, ISO 8601 (e.g. 2026-08-07T17:00).",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": (
                "List the user's tasks, ordered by urgency. Defaults to active tasks; "
                "pass status to filter (todo, in_progress, done, dropped)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "done", "dropped"],
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Change a task's title, notes, priority, status, due date, or snooze.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "The task's id."},
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "priority": {"type": "integer", "enum": [1, 2, 3]},
                    "status": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "done", "dropped"],
                    },
                    "due_at": {"type": "string", "description": "ISO 8601 date/time."},
                    "snoozed_until": {"type": "string", "description": "ISO 8601 date/time."},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task done.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": (
                "Permanently delete a task. Destructive — only after the user confirms."
            ),
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        },
    },
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


# --- argument parsing helpers (raise Invalid so the model gets a clear message) ---


def _parse_dt(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise Invalid(f"'{value}' is not a valid ISO 8601 date/time") from exc
    if parsed.tzinfo is None:  # assume the user's timezone when none is given
        parsed = parsed.replace(tzinfo=ZoneInfo(settings.app_timezone))
    return parsed


def _parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise Invalid(f"'{value}' is not a valid ISO date (YYYY-MM-DD)") from exc


def _parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise Invalid(f"'{value}' is not a valid id") from exc


# --- result serializers (JSON-safe summaries fed back to the model) --------------


def _task_summary(t: Task) -> dict:
    return {
        "id": str(t.id),
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "notes": t.notes,
        "snoozed_until": t.snoozed_until.isoformat() if t.snoozed_until else None,
    }


def _entry_summary(e: JournalEntry) -> dict:
    return {
        "id": str(e.id),
        "entry_date": e.entry_date.isoformat(),
        "content": e.content,
        "mood": e.mood,
        "tags": list(e.tags or []),
    }


# --- tool implementations --------------------------------------------------------


def _create_task(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    task = tasks_svc.create_task(
        db,
        user_id,
        title=a.get("title", ""),
        notes=a.get("notes"),
        priority=int(a.get("priority", 2)),
        due_at=_parse_dt(a["due_at"]) if a.get("due_at") else None,
    )
    return _task_summary(task)


def _list_tasks(db: Session, user_id: uuid.UUID, a: dict) -> list[dict]:
    return [_task_summary(t) for t in tasks_svc.list_tasks(db, user_id, a.get("status"))]


def _update_task(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    fields: dict = {}
    for key in ("title", "notes", "status"):
        if a.get(key) is not None:
            fields[key] = a[key]
    if a.get("priority") is not None:
        fields["priority"] = int(a["priority"])
    if a.get("due_at"):
        fields["due_at"] = _parse_dt(a["due_at"])
    if a.get("snoozed_until"):
        fields["snoozed_until"] = _parse_dt(a["snoozed_until"])
    task = tasks_svc.update_task(db, user_id, _parse_id(a["task_id"]), **fields)
    return _task_summary(task)


def _complete_task(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    return _task_summary(tasks_svc.complete_task(db, user_id, _parse_id(a["task_id"])))


def _delete_task(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    task_id = _parse_id(a["task_id"])
    tasks_svc.delete_task(db, user_id, task_id)
    return {"deleted": True, "id": str(task_id)}


def _add_journal_entry(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    entry = journal_svc.add_entry(
        db,
        user_id,
        content=a.get("content", ""),
        mood=int(a["mood"]) if a.get("mood") is not None else None,
        tags=a.get("tags"),
        channel="assistant",
    )
    return _entry_summary(entry)


def _list_journal(db: Session, user_id: uuid.UUID, a: dict) -> list[dict]:
    rows = journal_svc.list_entries(
        db,
        user_id,
        start=_parse_date(a["start"]) if a.get("start") else None,
        end=_parse_date(a["end"]) if a.get("end") else None,
    )
    return [_entry_summary(e) for e in rows]


_DISPATCH: dict[str, Callable[[Session, uuid.UUID, dict], object]] = {
    "create_task": _create_task,
    "list_tasks": _list_tasks,
    "update_task": _update_task,
    "complete_task": _complete_task,
    "delete_task": _delete_task,
    "add_journal_entry": _add_journal_entry,
    "list_journal": _list_journal,
}


def execute(db: Session, user_id: uuid.UUID, name: str, arguments: dict) -> dict:
    """Run one tool call and return a structured result. Never raises: unknown
    tools, invalid input, missing records, and internal errors all become an
    `{"ok": False, "error": ...}` the model can recover from."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown tool '{name}'"}
    try:
        return {"ok": True, "result": fn(db, user_id, arguments or {})}
    except Duplicate as exc:
        # Hand the existing record back so the assistant can point at it ("you already
        # have that one") instead of creating a second copy.
        existing = _task_summary(exc.existing) if isinstance(exc.existing, Task) else None
        return {"ok": False, "error": str(exc), "existing": existing}
    except (Invalid, NotFound) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:  # noqa: BLE001 - a tool must never crash the chat turn
        log.warning("tool '%s' failed", name, exc_info=True)
        return {"ok": False, "error": "the tool failed to run"}
