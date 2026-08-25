"""Test fixtures. Uses the real Postgres (models need PG-only types), but scopes
all data to dedicated test emails so a shared dev DB's real rows are untouched.
The LLM is replaced with a fake async generator so tests never hit the network.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db.models import (
    ChatSession,
    DailyUsage,
    GeneratedReview,
    JobRun,
    JournalEntry,
    Message,
    Notification,
    ProfileFact,
    PushSubscription,
    Span,
    Task,
    Turn,
    User,
    UserJobPref,
)
from app.db.session import SessionLocal
from app.main import app

TEST_EMAIL = "pytest-user@example.com"
TEST_PASSWORD = "pytest-secret-123"
OTHER_EMAIL = "pytest-other@example.com"
_ALL_TEST_EMAILS = (TEST_EMAIL, OTHER_EMAIL)

#: Prefix for test job names AND test occurrence keys, so `job_runs` can be cleaned
#: without touching real scheduled runs on a shared development database.
#:
#: Both are matched, because the two kinds of test need different things: a test with its
#: own synthetic job is identified by NAME, while a test exercising a real job (the
#: retention sweep) keeps that job's name and marks the OCCURRENCE instead.
TEST_PREFIX = "pytest-job-"


def _purge(db):
    users = db.execute(select(User).where(User.email.in_(_ALL_TEST_EMAILS))).scalars().all()
    for u in users:
        sids = [
            s.id
            for s in db.execute(select(ChatSession).where(ChatSession.user_id == u.id)).scalars()
        ]
        if sids:
            db.execute(delete(Message).where(Message.session_id.in_(sids)))
        # Traces reference the user, so they must go before it. Spans cascade from turns,
        # but are deleted explicitly so a future change to that FK cannot leave orphans.
        turn_ids = [t.id for t in db.execute(select(Turn).where(Turn.user_id == u.id)).scalars()]
        if turn_ids:
            db.execute(delete(Span).where(Span.turn_id.in_(turn_ids)))
        db.execute(delete(Turn).where(Turn.user_id == u.id))
        # The rollup outlives the turns behind it by design, so it needs its own delete —
        # and it references the user, so leaving rows here would break the purge entirely.
        db.execute(delete(DailyUsage).where(DailyUsage.user_id == u.id))
        db.execute(delete(ChatSession).where(ChatSession.user_id == u.id))
        db.execute(delete(ProfileFact).where(ProfileFact.user_id == u.id))
        db.execute(delete(Task).where(Task.user_id == u.id))
        db.execute(delete(JournalEntry).where(JournalEntry.user_id == u.id))
        # Migration 011. Every one of these references the user, so a missing delete here
        # does not leak rows — it breaks the purge outright with a foreign key violation,
        # which is how this list stays complete.
        db.execute(delete(Notification).where(Notification.user_id == u.id))
        db.execute(delete(PushSubscription).where(PushSubscription.user_id == u.id))
        db.execute(delete(UserJobPref).where(UserJobPref.user_id == u.id))
        db.execute(delete(GeneratedReview).where(GeneratedReview.user_id == u.id))
    db.execute(delete(User).where(User.email.in_(_ALL_TEST_EMAILS)))
    # `job_runs` has no user column, so it cannot be scoped by test email. It is scoped by
    # the TEST_PREFIX on either the job name or the occurrence key. Deleting every row would
    # destroy the real run history on a shared dev database — the same reason every other
    # delete here is scoped rather than a TRUNCATE.
    db.execute(
        delete(JobRun).where(
            JobRun.job_name.like(f"{TEST_PREFIX}%") | JobRun.occurrence_key.like(f"{TEST_PREFIX}%")
        )
    )
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


@pytest.fixture
def other_user(db):
    """A second user, to prove data is scoped and never leaks across users."""
    u = User(email=OTHER_EMAIL, password_hash=hash_password("other-secret-123"))
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
    # The handler drives chat through `stream_with_tools`, which yields
    # (kind, payload) events. The default fake never calls tools — it just streams
    # the same "Hello, there." reply. Tool-loop tests override this per test.
    async def _fake_stream_with_tools(
        messages, tools=None, model=None, usage=None, effort=None, provider=None
    ):
        if usage is not None:
            usage["tokens_in"] = 5
            usage["tokens_out"] = 3
        for tok in ["Hello", ", ", "there", "."]:
            yield "delta", tok

    async def _fake_embed(texts, usage=None):
        return [fake_embed_vec(t) for t in texts]

    async def _fake_complete(messages, model=None, effort=None, provider=None, usage=None):
        return "[]"  # no facts by default; memory tests override this

    monkeypatch.setattr("app.core.llm.stream_with_tools", _fake_stream_with_tools)
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


@pytest.fixture
def jobs_registry():
    """Give a test the job registry to itself.

    Tests that exercise the scheduler must not run the REAL jobs — `tick` would fire the
    digests, call a model, and write briefings into the developer's own database. So the
    registry is swapped for an empty one and restored afterwards.

    Reaching into `_REGISTRY` is deliberate. The alternative is a public "unregister"
    function that exists only for tests and that production code could then call.
    """
    from app.jobs import registry

    saved = dict(registry._REGISTRY)
    registry._REGISTRY.clear()
    try:
        yield registry
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


@pytest.fixture(autouse=True)
def _no_vapid_by_default(monkeypatch):
    """Every test starts with push UNCONFIGURED, whatever is in the developer's `.env`.

    Without this the suite's result depends on the machine it runs on. Eight tests assert
    the unconfigured behaviour — "a notification is recorded even though delivery is
    impossible" — and they passed only because CI has no keys and a fresh checkout has no
    keys. The moment real VAPID keys were added to a local `.env` in order to test push on a
    phone, those eight began failing on that machine alone, while CI stayed green.

    A suite whose answer depends on an untracked file is not a suite anybody can trust: it
    reports a fault that is not in the code, and it would just as happily hide one that is.

    `fake_push` sets its own generated keys on top of this, so tests that need push
    configured are unaffected.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "vapid_public_key", "")
    monkeypatch.setattr(settings, "vapid_private_key", "")


@pytest.fixture(autouse=True)
def _no_push_ceiling(monkeypatch):
    """And with no delivery ceiling, which is now the default.

    Pinned explicitly rather than inherited so that a test asserting ceiling behaviour has
    to SET one — a test that passes only because of a default is a test that silently
    changes meaning when the default does.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "daily_push_cap", 0)


@pytest.fixture
def fake_push(monkeypatch):
    """A push transport that records what would have been sent.

    Encryption and VAPID signing stay REAL — only the network call is replaced — so the
    parts most likely to be wrong are genuinely exercised in CI. Returns the list of
    (endpoint, body, headers) tuples, plus a `status` attribute the test can set to
    simulate a push service refusing.
    """
    from app.config import settings
    from app.core import push
    from app.scripts.generate_vapid import generate

    public, private = generate()
    monkeypatch.setattr(settings, "vapid_public_key", public)
    monkeypatch.setattr(settings, "vapid_private_key", private)
    monkeypatch.setattr(settings, "vapid_subject", "mailto:pytest@example.com")

    class Recorder(list):
        status = 201

        def __call__(self, endpoint, body, headers):
            self.append((endpoint, body, headers))
            return self.status

    recorder = Recorder()
    # Patched at the module level rather than passed in, so it applies to every caller —
    # `raise_notification` does not thread a transport through, and it should not have to
    # carry a parameter that exists only for tests.
    monkeypatch.setattr(push, "_http_post", recorder)
    return recorder


def make_subscription():
    """A synthetic browser subscription, with real P-256 keys so encryption succeeds."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    client = ec.generate_private_key(ec.SECP256R1())
    raw = client.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/PYTEST-ENDPOINT",
        "p256dh": b64(raw),
        "auth": b64(b"0123456789abcdef"),
    }
