"""Task tools: what the assistant may do to the user's to-do list.

Schemas and handlers live in the same file on purpose — a schema without a handler is a
tool the model will call and that always fails, and a handler without a schema is dead
code. Keeping them adjacent makes both mistakes visible at a glance, and `__init__`
asserts the pairing.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.tools.common import parse_dt, parse_id
from app.db.models import Task
from app.services import tasks as tasks_svc

SCHEMAS: list[dict] = [
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
]


def summary(t: Task) -> dict:
    return {
        "id": str(t.id),
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "notes": t.notes,
        "snoozed_until": t.snoozed_until.isoformat() if t.snoozed_until else None,
    }


def _create_task(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    task = tasks_svc.create_task(
        db,
        user_id,
        title=a.get("title", ""),
        notes=a.get("notes"),
        priority=int(a.get("priority", 2)),
        due_at=parse_dt(a["due_at"]) if a.get("due_at") else None,
    )
    return summary(task)


def _list_tasks(db: Session, user_id: uuid.UUID, a: dict) -> list[dict]:
    return [summary(t) for t in tasks_svc.list_tasks(db, user_id, a.get("status"))]


def _update_task(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    fields: dict = {}
    for key in ("title", "notes", "status"):
        if a.get(key) is not None:
            fields[key] = a[key]
    if a.get("priority") is not None:
        fields["priority"] = int(a["priority"])
    if a.get("due_at"):
        fields["due_at"] = parse_dt(a["due_at"])
    if a.get("snoozed_until"):
        fields["snoozed_until"] = parse_dt(a["snoozed_until"])
    task = tasks_svc.update_task(db, user_id, parse_id(a["task_id"]), **fields)
    return summary(task)


def _complete_task(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    return summary(tasks_svc.complete_task(db, user_id, parse_id(a["task_id"])))


def _delete_task(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    task_id = parse_id(a["task_id"])
    tasks_svc.delete_task(db, user_id, task_id)
    return {"deleted": True, "id": str(task_id)}


HANDLERS = {
    "create_task": _create_task,
    "list_tasks": _list_tasks,
    "update_task": _update_task,
    "complete_task": _complete_task,
    "delete_task": _delete_task,
}
