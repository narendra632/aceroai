"""Task service: create/read/update/complete/snooze/delete, always user-scoped.

Urgency is **derived at read time** (never stored) from due date, priority, and
snooze — see `urgency_key`. `list_tasks` returns rows already ordered by it, so the
UI and the assistant share one notion of "what's urgent".
"""

import datetime as dt
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Task
from app.services.errors import Duplicate, Invalid, NotFound

ACTIVE_STATUSES = ("todo", "in_progress")
_VALID_STATUSES = ("todo", "in_progress", "done", "dropped")
_PRIORITIES = (1, 2, 3)  # 1 high · 2 mid · 3 low
_FAR_FUTURE = dt.datetime.max.replace(tzinfo=dt.UTC)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def urgency_key(task: Task, now: dt.datetime | None = None) -> tuple:
    """Sort key (ascending = most urgent first). A task snoozed into the future
    sinks to the bottom; otherwise overdue outranks due-soon, then priority, with
    undated tasks after dated ones."""
    now = now or _now()
    snoozed = task.snoozed_until is not None and task.snoozed_until > now
    if task.due_at is not None:
        bucket = 0 if task.due_at <= now else 1  # overdue before upcoming
        due_sort = task.due_at
    else:
        bucket = 2  # undated tasks come after anything with a due date
        due_sort = _FAR_FUTURE
    return (snoozed, bucket, due_sort, task.priority, task.created_at)


def sort_by_urgency(tasks: list[Task], now: dt.datetime | None = None) -> list[Task]:
    now = now or _now()
    return sorted(tasks, key=lambda t: urgency_key(t, now))


def _validate_priority(priority: int) -> None:
    if priority not in _PRIORITIES:
        raise Invalid("priority must be 1 (high), 2 (mid), or 3 (low)")


def _normalize(title: str) -> str:
    """Fold a title to a comparable form: case, punctuation and spacing don't matter."""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def find_duplicate(db: Session, user_id: uuid.UUID, title: str) -> Task | None:
    """An existing *active* task whose title means the same thing.

    Deliberately conservative — it catches "Pay rent" vs "pay rent!" but not
    differently-worded tasks. The assistant is the smart layer here (it sees the open
    list in its context); this is the backstop that stops an obvious silent duplicate
    when the model slips.
    """
    target = _normalize(title)
    if not target:
        return None
    for task in list_tasks(db, user_id):
        if _normalize(task.title) == target:
            return task
    return None


def get_task(db: Session, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user_id:
        raise NotFound("task not found")
    return task


def list_tasks(db: Session, user_id: uuid.UUID, status: str | None = None) -> list[Task]:
    """Active tasks (todo + in_progress) by default, ordered by derived urgency.
    Pass an explicit `status` (e.g. "done") to list a single status instead."""
    stmt = select(Task).where(Task.user_id == user_id)
    if status is not None:
        if status not in _VALID_STATUSES:
            raise Invalid(f"status must be one of {_VALID_STATUSES}")
        stmt = stmt.where(Task.status == status)
    else:
        stmt = stmt.where(Task.status.in_(ACTIVE_STATUSES))
    rows = list(db.execute(stmt).scalars().all())
    return sort_by_urgency(rows)


def create_task(
    db: Session,
    user_id: uuid.UUID,
    title: str,
    notes: str | None = None,
    priority: int = 2,
    due_at: dt.datetime | None = None,
    allow_duplicate: bool = False,
) -> Task:
    title = (title or "").strip()
    if not title:
        raise Invalid("a task needs a title")
    _validate_priority(priority)
    if not allow_duplicate:
        existing = find_duplicate(db, user_id, title)
        if existing is not None:
            raise Duplicate(f"an open task called '{existing.title}' already exists", existing)
    task = Task(user_id=user_id, title=title, notes=notes, priority=priority, due_at=due_at)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(
    db: Session,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    title: str | None = None,
    notes: str | None = None,
    priority: int | None = None,
    status: str | None = None,
    due_at: dt.datetime | None = None,
    snoozed_until: dt.datetime | None = None,
) -> Task:
    """Partial update: only the fields passed (non-None) are changed. Completing a
    task is done via `complete_task`, but setting status here is also honored."""
    task = get_task(db, user_id, task_id)
    if title is not None:
        title = title.strip()
        if not title:
            raise Invalid("a task needs a title")
        task.title = title
    if notes is not None:
        task.notes = notes
    if priority is not None:
        _validate_priority(priority)
        task.priority = priority
    if status is not None:
        if status not in _VALID_STATUSES:
            raise Invalid(f"status must be one of {_VALID_STATUSES}")
        task.status = status
        task.completed_at = _now() if status == "done" else None
    if due_at is not None:
        task.due_at = due_at
    if snoozed_until is not None:
        task.snoozed_until = snoozed_until
    db.commit()
    db.refresh(task)
    return task


def complete_task(db: Session, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = get_task(db, user_id, task_id)
    task.status = "done"
    task.completed_at = _now()
    db.commit()
    db.refresh(task)
    return task


def snooze_task(db: Session, user_id: uuid.UUID, task_id: uuid.UUID, until: dt.datetime) -> Task:
    task = get_task(db, user_id, task_id)
    task.snoozed_until = until
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, user_id: uuid.UUID, task_id: uuid.UUID) -> None:
    task = get_task(db, user_id, task_id)
    db.delete(task)
    db.commit()
