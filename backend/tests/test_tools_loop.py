"""The assistant's tool-use loop, driven through the chat endpoint with a scripted
fake LLM. Covers: acting via tools (create/complete/journal), user scoping, recovery
from a malformed call, and the iteration cap."""

import json

from app.config import settings
from app.services import journal as journal_svc
from app.services import tasks as tasks_svc
from tests.test_chat import _parse_sse


def _scripted(*turns):
    """Return a fake `stream_with_tools`. Each successive handler call consumes the
    next turn (a list of (kind, payload) events); the final turn repeats."""
    state = {"i": 0}

    async def fake(
        messages, tools=None, model=None, max_tokens=8192, usage=None, reasoning_effort=None
    ):
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        for kind, payload in turn:
            yield kind, payload

    return fake


def _call(id_, name, args):
    return {"id": id_, "name": name, "arguments": json.dumps(args)}


def test_assistant_creates_task_via_tool(auth_client, db, user, monkeypatch):
    fake = _scripted(
        [("tool_calls", [_call("c1", "create_task", {"title": "Pay rent"})])],
        [("delta", "Done — added it.")],
    )
    monkeypatch.setattr("app.core.llm.stream_with_tools", fake)

    events = _parse_sse(auth_client.post("/api/chat", json={"message": "add task pay rent"}).text)
    kinds = [e for e, _ in events]
    assert "tool" in kinds  # the "working…" signal reached the client
    assert kinds[-1] == "done"
    assert "".join(d for e, d in events if e == "delta") == "Done — added it."

    assert [t.title for t in tasks_svc.list_tasks(db, user.id)] == ["Pay rent"]


def test_assistant_completes_task_via_tool(auth_client, db, user, monkeypatch):
    task = tasks_svc.create_task(db, user.id, title="ship it")
    fake = _scripted(
        [("tool_calls", [_call("c1", "complete_task", {"task_id": str(task.id)})])],
        [("delta", "Marked done.")],
    )
    monkeypatch.setattr("app.core.llm.stream_with_tools", fake)

    auth_client.post("/api/chat", json={"message": "complete ship it"})
    db.refresh(task)
    assert task.status == "done"


def test_assistant_journals_via_tool(auth_client, db, user, monkeypatch):
    fake = _scripted(
        [("tool_calls", [_call("c1", "add_journal_entry", {"content": "went well", "mood": 4})])],
        [("delta", "Logged.")],
    )
    monkeypatch.setattr("app.core.llm.stream_with_tools", fake)

    auth_client.post("/api/chat", json={"message": "journal that today went well, mood 4"})
    entries = journal_svc.list_entries(db, user.id)
    assert entries[0].content == "went well"
    assert entries[0].mood == 4
    assert entries[0].channel == "assistant"  # origin recorded


def test_malformed_tool_call_recovers(auth_client, db, user, monkeypatch):
    fake = _scripted(
        [("tool_calls", [{"id": "c1", "name": "create_task", "arguments": "{not valid json"}])],
        [("delta", "Sorry, could you rephrase?")],
    )
    monkeypatch.setattr("app.core.llm.stream_with_tools", fake)

    events = _parse_sse(auth_client.post("/api/chat", json={"message": "add something"}).text)
    assert events[-1][0] == "done"  # turn still completes
    assert "".join(d for e, d in events if e == "delta") == "Sorry, could you rephrase?"
    assert tasks_svc.list_tasks(db, user.id) == []  # nothing created


def test_tool_cannot_touch_other_users_task(auth_client, db, user, other_user, monkeypatch):
    task = tasks_svc.create_task(db, other_user.id, title="theirs")
    fake = _scripted(
        [("tool_calls", [_call("c1", "complete_task", {"task_id": str(task.id)})])],
        [("delta", "I couldn't find that task.")],
    )
    monkeypatch.setattr("app.core.llm.stream_with_tools", fake)

    auth_client.post("/api/chat", json={"message": "complete theirs"})
    db.refresh(task)
    assert task.status == "todo"  # never modified across users


def test_tool_loop_is_bounded(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "tools_max_iters", 3)

    async def always_tool(
        messages, tools=None, model=None, max_tokens=8192, usage=None, reasoning_effort=None
    ):
        # never answers with text — would loop forever if unbounded
        yield "tool_calls", [_call("c", "list_tasks", {})]

    monkeypatch.setattr("app.core.llm.stream_with_tools", always_tool)

    events = _parse_sse(auth_client.post("/api/chat", json={"message": "loop please"}).text)
    assert len([e for e, _ in events if e == "tool"]) == 3  # capped, not infinite
    assert events[-1][0] == "done"
