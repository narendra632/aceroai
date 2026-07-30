"""Test fixtures. Uses the real Postgres (models need PG-only types), but scopes
all data to dedicated test emails so a shared dev DB's real rows are untouched.
The LLM is replaced with a fake async generator so tests never hit the network.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db.models import ChatSession, Message, ProfileFact, User
from app.db.session import SessionLocal
from app.main import app

TEST_EMAIL = "pytest-user@example.com"
TEST_PASSWORD = "pytest-secret-123"
OTHER_EMAIL = "pytest-other@example.com"
_ALL_TEST_EMAILS = (TEST_EMAIL, OTHER_EMAIL)


def _purge(db):
    users = db.execute(select(User).where(User.email.in_(_ALL_TEST_EMAILS))).scalars().all()
    for u in users:
        sids = [
            s.id
            for s in db.execute(select(ChatSession).where(ChatSession.user_id == u.id)).scalars()
        ]
        if sids:
            db.execute(delete(Message).where(Message.session_id.in_(sids)))
        db.execute(delete(ChatSession).where(ChatSession.user_id == u.id))
        db.execute(delete(ProfileFact).where(ProfileFact.user_id == u.id))
    db.execute(delete(User).where(User.email.in_(_ALL_TEST_EMAILS)))
    db.commit()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean(db):
    _purge(db)
    yield
    _purge(db)


@pytest.fixture
def user(db):
    u = User(email=TEST_EMAIL, password_hash=hash_password(TEST_PASSWORD))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def fake_embed_vec(text: str) -> list[float]:
    """Deterministic pseudo-embedding of the right dimension for tests — no network."""
    from app.config import settings

    vec = [0.0] * settings.embed_dim
    for i, ch in enumerate(text):
        vec[(i * 7 + ord(ch)) % settings.embed_dim] += 1.0
    return vec


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    async def _fake_stream(
        messages, model=None, max_tokens=8192, usage=None, reasoning_effort=None
    ):
        if usage is not None:
            usage["tokens_in"] = 5
            usage["tokens_out"] = 3
        for tok in ["Hello", ", ", "there", "."]:
            yield tok

    async def _fake_embed(texts):
        return [fake_embed_vec(t) for t in texts]

    async def _fake_complete(messages, model=None, max_tokens=8192, reasoning_effort=None):
        return "[]"  # no facts by default; memory tests override this

    monkeypatch.setattr("app.core.llm.stream_chat", _fake_stream)
    monkeypatch.setattr("app.core.llm.embed", _fake_embed)
    monkeypatch.setattr("app.core.llm.complete", _fake_complete)
    # Keep handler-driven tests deterministic — no background extraction tasks.
    # Memory tests call extract_and_store directly, bypassing this switch.
    monkeypatch.setattr("app.config.settings.memory_extraction_enabled", False)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_client(client, user):
    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert r.status_code == 200
    return client
