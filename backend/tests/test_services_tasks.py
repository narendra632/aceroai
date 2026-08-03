"""Task service: CRUD, status lifecycle, derived-urgency ordering, user scoping."""

import datetime as dt

import pytest

from app.services import tasks as svc
from app.services.errors import Invalid, NotFound


def _dt(days: float) -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(days=days)


def test_create_defaults_and_validation(db, user):
    task = svc.create_task(db, user.id, title="  Pay rent  ")
    assert task.title == "Pay rent"  # trimmed
    assert task.status == "todo"
    assert task.priority == 2

    with pytest.raises(Invalid):
        svc.create_task(db, user.id, title="   ")
    with pytest.raises(Invalid):
        svc.create_task(db, user.id, title="ok", priority=9)


def test_complete_sets_status_and_timestamp(db, user):
    task = svc.create_task(db, user.id, title="ship it")
    done = svc.complete_task(db, user.id, task.id)
    assert done.status == "done"
    assert done.completed_at is not None


def test_update_rejects_bad_status(db, user):
    task = svc.create_task(db, user.id, title="x")
    with pytest.raises(Invalid):
        svc.update_task(db, user.id, task.id, status="nope")


def test_list_defaults_to_active_only(db, user):
    svc.create_task(db, user.id, title="active")
    done = svc.create_task(db, user.id, title="finished")
    svc.complete_task(db, user.id, done.id)

    titles = [t.title for t in svc.list_tasks(db, user.id)]
    assert titles == ["active"]
    assert [t.title for t in svc.list_tasks(db, user.id, status="done")] == ["finished"]


def test_urgency_ordering(db, user):
    svc.create_task(db, user.id, title="overdue", due_at=_dt(-1))
    svc.create_task(db, user.id, title="soon", due_at=_dt(1))
    svc.create_task(db, user.id, title="undated", priority=1)
    snoozed = svc.create_task(db, user.id, title="snoozed", due_at=_dt(-2))
    svc.snooze_task(db, user.id, snoozed.id, _dt(1))

    order = [t.title for t in svc.list_tasks(db, user.id)]
    assert order == ["overdue", "soon", "undated", "snoozed"]


def test_scoping_foreign_task_is_not_found(db, user, other_user):
    task = svc.create_task(db, user.id, title="mine")
    with pytest.raises(NotFound):
        svc.get_task(db, other_user.id, task.id)
    with pytest.raises(NotFound):
        svc.complete_task(db, other_user.id, task.id)
    # untouched for the real owner
    assert svc.get_task(db, user.id, task.id).status == "todo"


def test_delete(db, user):
    task = svc.create_task(db, user.id, title="temp")
    svc.delete_task(db, user.id, task.id)
    with pytest.raises(NotFound):
        svc.get_task(db, user.id, task.id)
