import json

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


# --- what the user is shown about memory ------------------------------------------


def _recall_fixture(db, user):
    """A fact whose wording matches the message below, so BOTH rankers find it."""
    from app.db.models import ProfileFact
    from tests.conftest import fake_embed_vec

    db.add(
        ProfileFact(
            user_id=user.id,
            fact="Narendra keeps a spare charger in his bag.",
            category="other",
            confidence=0.9,
            source="inferred",
            status="active",
            embedding=fake_embed_vec("Narendra keeps a spare charger in his bag."),
        )
    )
    db.commit()


def test_recall_event_lists_exactly_what_the_model_was_sent(auth_client, db, user, monkeypatch):
    """A display that can drift from what was used is worse than no display.

    The prompt the model actually received is captured and compared against the `recall`
    frame the browser is sent. Anything less would let the two diverge silently, which is
    the exact class of bug this whole change exists to make visible.
    """
    _recall_fixture(db, user)
    seen: dict = {}

    async def capture(messages, tools=None, model=None, usage=None, effort=None, provider=None):
        seen["blocks"] = [m["content"] for m in messages if m["role"] == "system"]
        yield "delta", "ok"

    monkeypatch.setattr("app.core.llm.stream_with_tools", capture)

    r = auth_client.post("/api/chat", json={"message": "where is my spare charger"})
    events = _parse_sse(r.text)

    recall = [d for e, d in events if e == "recall"]
    assert recall, "the browser must be told which facts were used"
    facts = json.loads(recall[0])
    assert facts, "this message matches a stored fact by both meaning and wording"

    prompt = "\n".join(seen["blocks"])
    for f in facts:
        assert f["fact"] in prompt  # shown == sent
        assert f["id"] in prompt  # and the id travels, so it can be corrected in one step
        assert f["via"] in ("both", "vector", "lexical")


def test_no_recall_event_when_nothing_was_relevant(auth_client, db, user):
    """The control is absent, not present-and-empty. After hybrid recall, recalling nothing
    is a normal outcome — an always-present button reading "none" would be noise on exactly
    the turns needing no explanation."""
    r = auth_client.post("/api/chat", json={"message": "explain quaternion interpolation"})
    assert "recall" not in [e for e, _ in _parse_sse(r.text)]
