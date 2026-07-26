from sqlalchemy import select

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
