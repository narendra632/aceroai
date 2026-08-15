from sqlalchemy import select

from app.config import settings
from app.db.models import ChatSession, Message, User
from tests.conftest import OTHER_EMAIL


def _parse_sse(text: str) -> list[tuple[str, str]]:
    """Parse SSE frames, preserving data content (SSE strips only one leading
    space after 'data:', not the whole field)."""
    events: list[tuple[str, str]] = []
    for frame in text.replace("\r\n", "\n").split("\n\n"):
        event = None
        data_parts: list[str] = []
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                chunk = line[len("data:") :]
                if chunk.startswith(" "):
                    chunk = chunk[1:]
                data_parts.append(chunk)
        if event is not None:
            events.append((event, "\n".join(data_parts)))
    return events


def test_chat_streams_and_persists(auth_client, db, user):
    r = auth_client.post("/api/chat", json={"message": "hi there"})
    assert r.status_code == 200

    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "session"
    assert "delta" in kinds
    assert kinds[-1] == "done"

    # the fake LLM streams "Hello, there."
    streamed = "".join(d for e, d in events if e == "delta")
    assert streamed == "Hello, there."

    session_id = events[0][1]
    msgs = (
        db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
        .scalars()
        .all()
    )
    assert [(m.role, m.content) for m in msgs] == [
        ("user", "hi there"),
        ("assistant", "Hello, there."),
    ]
    assert msgs[1].model is not None
    assert msgs[1].tokens_out == 3


def test_new_session_created_and_listed(auth_client, db, user):
    auth_client.post("/api/chat", json={"message": "first message ever"})
    sessions = auth_client.get("/api/chat/sessions").json()
    assert len(sessions) == 1
    assert sessions[0]["title"] == "first message ever"
    assert sessions[0]["channel"] == "web"


def test_history_endpoint(auth_client):
    sid = _parse_sse(auth_client.post("/api/chat", json={"message": "remember this"}).text)[0][1]
    history = auth_client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "remember this"


def test_reasoning_effort_forwarded(auth_client, monkeypatch):
    captured: dict = {}

    async def recorder(messages, tools=None, model=None, usage=None, effort=None, provider=None):
        captured["effort"] = effort
        yield "delta", "ok"

    monkeypatch.setattr("app.core.llm.stream_with_tools", recorder)
    auth_client.post("/api/chat", json={"message": "hi"})
    assert captured["effort"] == settings.reasoning_effort_chat


def test_deep_flag_routes_high_reasoning(auth_client, monkeypatch):
    captured: dict = {}

    async def recorder(messages, tools=None, model=None, usage=None, effort=None, provider=None):
        captured["effort"] = effort
        yield "delta", "ok"

    monkeypatch.setattr("app.core.llm.stream_with_tools", recorder)
    auth_client.post("/api/chat", json={"message": "hi", "deep": True})
    assert captured["effort"] == settings.reasoning_effort_deep


def test_provider_error_reported_without_leaking(auth_client, monkeypatch):
    async def boom(messages, tools=None, model=None, usage=None, effort=None, provider=None):
        if False:
            yield "delta", ""  # make this an async generator
        raise RuntimeError("SECRET internal provider detail")

    monkeypatch.setattr("app.core.llm.stream_with_tools", boom)
    events = _parse_sse(auth_client.post("/api/chat", json={"message": "hi"}).text)

    errors = [d for e, d in events if e == "error"]
    assert errors, "expected an error event"
    assert "SECRET internal provider detail" not in errors[0]
    assert "went wrong" in errors[0].lower()


def test_overlong_message_rejected_before_persisting(auth_client, db, user):
    big = "x" * (settings.max_input_chars + 1)
    events = _parse_sse(auth_client.post("/api/chat", json={"message": big}).text)

    assert events[0][0] == "error"
    assert "too long" in events[0][1].lower()
    # nothing persisted: no session, no messages for this user
    sessions = db.execute(select(ChatSession).where(ChatSession.user_id == user.id)).scalars().all()
    assert sessions == []


def test_cannot_access_other_users_session(auth_client, db):
    other = User(email=OTHER_EMAIL, password_hash="x")
    db.add(other)
    db.commit()
    other_session = ChatSession(user_id=other.id, channel="web", title="theirs")
    db.add(other_session)
    db.commit()
    db.refresh(other_session)

    assert auth_client.get(f"/api/chat/sessions/{other_session.id}/messages").status_code == 404
    assert (
        auth_client.post(
            "/api/chat", json={"message": "hi", "session_id": str(other_session.id)}
        ).status_code
        == 404
    )
