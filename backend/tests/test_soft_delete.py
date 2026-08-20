"""Soft delete: a deleted record must be invisible to EVERY reader, and restorable.

The filter lives in the `services/` query builders precisely so there is one place to
get it right. These tests check each consumer of that layer independently — the REST
API, the assistant's tools, and (most importantly) the composer's injected task block.

The composer path is the one that matters most: a leak there feeds a deleted task
straight into the model's context, where it would confidently act on something the user
believes is gone.
"""

import asyncio
import datetime as dt

import pytest

from app.core import composer, tools
from app.core.handler import handle_message
from app.db.models import ChatSession, Message
from app.services import journal as journal_svc
from app.services import sessions as sessions_svc
from app.services import tasks as tasks_svc
from app.services.errors import NotFound

# --- tasks ---------------------------------------------------------------------


def test_deleted_task_is_invisible_to_every_reader(db, user):
    task = tasks_svc.create_task(db, user.id, title="Book bus ticket to Pune")
    tasks_svc.delete_task(db, user.id, task.id)

    # the service
    assert tasks_svc.list_tasks(db, user.id) == []
    # direct fetch behaves exactly as for a task that never existed
    with pytest.raises(NotFound):
        tasks_svc.get_task(db, user.id, task.id)
    # the assistant's tools
    listed = asyncio.run(tools.execute(db, user.id, "list_tasks", {}))
    assert all(t["id"] != str(task.id) for t in listed.get("tasks", []))


def test_deleted_task_never_reaches_the_model_context(db, user):
    """The critical one: the composer injects open tasks into every turn."""
    tasks_svc.create_task(db, user.id, title="Buy gifts for sisters")
    gone = tasks_svc.create_task(db, user.id, title="Cancel the gym membership")
    tasks_svc.delete_task(db, user.id, gone.id)

    session = ChatSession(user_id=user.id, channel="web")
    db.add(session)
    db.commit()

    blob = "\n".join(m["content"] for m in composer.build_context(db, session.id, user=user))
    assert "Buy gifts for sisters" in blob
    assert "Cancel the gym membership" not in blob
    assert str(gone.id) not in blob


def test_deleted_task_does_not_block_recreating_the_same_title(db, user):
    """A deleted task must not linger as a duplicate — that would look like the app
    refusing to work for no visible reason."""
    first = tasks_svc.create_task(db, user.id, title="Pay rent")
    tasks_svc.delete_task(db, user.id, first.id)

    assert tasks_svc.find_duplicate(db, user.id, "Pay rent") is None
    again = tasks_svc.create_task(db, user.id, title="Pay rent")
    assert again.id != first.id


def test_restore_returns_the_task_with_the_same_identity(db, user):
    task = tasks_svc.create_task(db, user.id, title="Renew passport", notes="appointment first")
    tasks_svc.delete_task(db, user.id, task.id)

    restored = tasks_svc.restore_task(db, user.id, task.id)
    assert restored.id == task.id
    assert restored.notes == "appointment first"
    assert [t.id for t in tasks_svc.list_tasks(db, user.id)] == [task.id]


def test_restoring_twice_is_not_an_error(db, user):
    """A double-tap on Undo must not fail."""
    task = tasks_svc.create_task(db, user.id, title="Water the plants")
    tasks_svc.delete_task(db, user.id, task.id)
    tasks_svc.restore_task(db, user.id, task.id)
    assert tasks_svc.restore_task(db, user.id, task.id).id == task.id


def test_restore_is_owner_scoped(db, user, other_user):
    task = tasks_svc.create_task(db, user.id, title="Private errand")
    tasks_svc.delete_task(db, user.id, task.id)
    with pytest.raises(NotFound):
        tasks_svc.restore_task(db, other_user.id, task.id)


def test_task_delete_and_restore_over_the_api(auth_client):
    created = auth_client.post("/api/tasks", json={"title": "Call the dentist"}).json()
    assert auth_client.delete(f"/api/tasks/{created['id']}").status_code == 204
    assert auth_client.get("/api/tasks").json() == []

    restored = auth_client.post(f"/api/tasks/{created['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["id"] == created["id"]
    assert [t["id"] for t in auth_client.get("/api/tasks").json()] == [created["id"]]


# --- journal -------------------------------------------------------------------


def test_deleted_journal_entry_is_invisible_and_restorable(db, user):
    entry = journal_svc.add_entry(db, user.id, content="Long day, good run.")
    journal_svc.delete_entry(db, user.id, entry.id)

    assert journal_svc.list_entries(db, user.id) == []
    with pytest.raises(NotFound):
        journal_svc.get_entry(db, user.id, entry.id)
    read = asyncio.run(tools.execute(db, user.id, "list_journal", {}))
    assert all(e["id"] != str(entry.id) for e in read.get("entries", []))

    restored = journal_svc.restore_entry(db, user.id, entry.id)
    assert restored.id == entry.id
    assert restored.content == "Long day, good run."


def test_journal_search_matches_content_and_skips_deleted(db, user):
    journal_svc.add_entry(db, user.id, content="Ran five kilometres this morning")
    journal_svc.add_entry(db, user.id, content="Read a chapter before bed")
    gone = journal_svc.add_entry(db, user.id, content="Ran errands all afternoon")
    journal_svc.delete_entry(db, user.id, gone.id)

    hits = journal_svc.list_entries(db, user.id, q="ran")
    assert [e.content for e in hits] == ["Ran five kilometres this morning"]


def test_journal_search_treats_wildcards_literally(db, user):
    journal_svc.add_entry(db, user.id, content="Finished 100% of the plan")
    journal_svc.add_entry(db, user.id, content="Nothing special today")
    assert len(journal_svc.list_entries(db, user.id, q="100%")) == 1


def test_journal_paging(db, user):
    for i in range(5):
        journal_svc.add_entry(db, user.id, content=f"entry {i}")
    assert len(journal_svc.list_entries(db, user.id, limit=2)) == 2
    assert len(journal_svc.list_entries(db, user.id, limit=2, offset=4)) == 1


# --- chat sessions -------------------------------------------------------------


def test_deleted_session_hides_but_keeps_its_messages(db, user):
    session = ChatSession(user_id=user.id, channel="web", title="Trip planning")
    db.add(session)
    db.commit()
    db.add(Message(session_id=session.id, role="user", content="where should we go?"))
    db.commit()

    sessions_svc.delete_session(db, user.id, session.id)
    assert sessions_svc.list_sessions(db, user.id) == []
    with pytest.raises(NotFound):
        sessions_svc.list_messages(db, user.id, session.id)

    # restoring returns the conversation intact — messages were never destroyed
    sessions_svc.restore_session(db, user.id, session.id)
    assert [m.content for m in sessions_svc.list_messages(db, user.id, session.id)] == [
        "where should we go?"
    ]


def test_session_rename(db, user):
    session = ChatSession(user_id=user.id, channel="web", title="hiii")
    db.add(session)
    db.commit()
    assert (
        sessions_svc.rename_session(db, user.id, session.id, "  Pune trip  ").title == "Pune trip"
    )


def test_session_rename_rejects_blank(db, user):
    from app.services.errors import Invalid

    session = ChatSession(user_id=user.id, channel="web")
    db.add(session)
    db.commit()
    with pytest.raises(Invalid):
        sessions_svc.rename_session(db, user.id, session.id, "   ")


def test_session_operations_are_owner_scoped(db, user, other_user):
    session = ChatSession(user_id=user.id, channel="web")
    db.add(session)
    db.commit()
    with pytest.raises(NotFound):
        sessions_svc.rename_session(db, other_user.id, session.id, "nope")
    with pytest.raises(NotFound):
        sessions_svc.delete_session(db, other_user.id, session.id)


def test_regenerate_drops_only_a_trailing_assistant_reply(db, user):
    session = ChatSession(user_id=user.id, channel="web")
    db.add(session)
    db.commit()
    base = dt.datetime.now(dt.UTC)
    db.add(Message(session_id=session.id, role="user", content="hello", created_at=base))
    db.add(
        Message(
            session_id=session.id,
            role="assistant",
            content="hi there",
            created_at=base + dt.timedelta(seconds=1),
        )
    )
    db.commit()

    sessions_svc.drop_last_reply(db, user.id, session.id)
    assert [m.role for m in sessions_svc.list_messages(db, user.id, session.id)] == ["user"]

    # nothing to regenerate when the user spoke last — a no-op, not an error
    sessions_svc.drop_last_reply(db, user.id, session.id)
    assert len(sessions_svc.list_messages(db, user.id, session.id)) == 1


def test_assistant_cannot_act_on_a_deleted_task(db, user):
    """End-to-end: the model is handed a task id that has since been deleted.

    `handle_message` is an async generator and this project has no async-test plugin, so
    it is driven explicitly with `asyncio.run` rather than an `async def` test — an
    un-awaited coroutine would be collected and reported as a pass without ever running.
    """
    task = tasks_svc.create_task(db, user.id, title="Something removed")
    tasks_svc.delete_task(db, user.id, task.id)

    result = asyncio.run(tools.execute(db, user.id, "complete_task", {"task_id": str(task.id)}))
    assert result["ok"] is False
    assert "not found" in result["error"].lower()

    async def _run() -> list[tuple[str, str]]:
        return [e async for e in handle_message(db, user, "did it get done?", "web", None)]

    events = asyncio.run(_run())
    # the turn still completes rather than failing
    assert any(kind == "delta" for kind, _ in events)
