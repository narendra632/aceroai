"""The assistant sees the user's open tasks every turn, and the service refuses an
obvious duplicate.

Why this matters: without the task list in context the model is blind — it duplicates
work it already created, needs an extra round-trip to act on a task, and can never
proactively surface something that's due (a prime directive in SOUL.md).
"""

import asyncio
import datetime as dt

import pytest

from app.config import settings
from app.core import composer
from app.db.models import ChatSession
from app.services import tasks as svc
from app.services.errors import Duplicate


def _session(db, user):
    s = ChatSession(user_id=user.id, channel="web", title="t")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _context_text(db, user) -> str:
    ctx = composer.build_context(db, _session(db, user).id, facts=None, user=user)
    return "\n".join(m["content"] for m in ctx if m["role"] == "system")


# --- context injection ---------------------------------------------------------------


def test_open_tasks_appear_in_context(db, user):
    svc.create_task(db, user.id, title="Pay rent", priority=1)
    text = _context_text(db, user)
    assert "Pay rent" in text
    assert "high priority" in text


def test_task_ids_are_available_so_it_can_act_in_one_step(db, user):
    task = svc.create_task(db, user.id, title="Book bus tickets")
    assert str(task.id) in _context_text(db, user)


def test_overdue_is_flagged(db, user):
    svc.create_task(
        db, user.id, title="Overdue thing", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
    )
    assert "OVERDUE" in _context_text(db, user)


def test_completed_tasks_are_not_shown(db, user):
    task = svc.create_task(db, user.id, title="Finished thing")
    svc.complete_task(db, user.id, task.id)
    assert "Finished thing" not in _context_text(db, user)


def test_empty_list_is_stated_explicitly(db, user):
    # "no open tasks" is information too — it stops the model inventing a list.
    assert "no open tasks" in _context_text(db, user).lower()


def test_context_is_capped(db, user, monkeypatch):
    monkeypatch.setattr(settings, "context_tasks_limit", 3)
    for i in range(6):
        svc.create_task(db, user.id, title=f"Task number {i}")
    shown = sum(f"Task number {i}" in _context_text(db, user) for i in range(6))
    assert shown == 3


def test_other_users_tasks_never_leak(db, user, other_user):
    svc.create_task(db, other_user.id, title="Their private task")
    assert "Their private task" not in _context_text(db, user)


def test_no_user_means_no_task_block(db, user):
    """Callers that don't pass a user (older signature) still work."""
    svc.create_task(db, user.id, title="Pay rent")
    ctx = composer.build_context(db, _session(db, user).id, facts=None)
    assert "Pay rent" not in "\n".join(m["content"] for m in ctx)


# --- duplicate backstop ---------------------------------------------------------------


def test_exact_duplicate_is_refused(db, user):
    svc.create_task(db, user.id, title="Pay rent")
    with pytest.raises(Duplicate) as exc:
        svc.create_task(db, user.id, title="Pay rent")
    assert exc.value.existing is not None
    assert len(svc.list_tasks(db, user.id)) == 1


def test_duplicate_check_ignores_case_and_punctuation(db, user):
    svc.create_task(db, user.id, title="Book bus tickets to Pune")
    with pytest.raises(Duplicate):
        svc.create_task(db, user.id, title="  book BUS tickets to pune!! ")


def test_differently_worded_task_is_allowed(db, user):
    """Deliberately conservative: the assistant judges wording, this only stops
    obvious repeats."""
    svc.create_task(db, user.id, title="Buy gifts for sisters")
    svc.create_task(db, user.id, title="Buy rakshabandhan presents")
    assert len(svc.list_tasks(db, user.id)) == 2


def test_completed_task_does_not_block_a_new_one(db, user):
    task = svc.create_task(db, user.id, title="Weekly review")
    svc.complete_task(db, user.id, task.id)
    svc.create_task(db, user.id, title="Weekly review")  # recurring work is fine
    assert len(svc.list_tasks(db, user.id)) == 1


def test_duplicate_can_be_forced(db, user):
    svc.create_task(db, user.id, title="Call mom")
    svc.create_task(db, user.id, title="Call mom", allow_duplicate=True)
    assert len(svc.list_tasks(db, user.id)) == 2


def test_api_returns_409_for_duplicate(auth_client):
    auth_client.post("/api/tasks", json={"title": "Pay rent"})
    r = auth_client.post("/api/tasks", json={"title": "pay rent"})
    assert r.status_code == 409


def test_tool_reports_existing_task_instead_of_creating(db, user):
    from app.core import tools

    svc.create_task(db, user.id, title="Pay rent")
    result = asyncio.run(tools.execute(db, user.id, "create_task", {"title": "Pay rent"}))
    assert result["ok"] is False
    assert result["existing"]["title"] == "Pay rent"  # so it can point at the real one
    assert len(svc.list_tasks(db, user.id)) == 1
