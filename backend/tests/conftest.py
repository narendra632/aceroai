"""Test fixtures. Uses the real Postgres (models need PG-only types), in a database of its
own. The LLM is replaced with a fake async generator so tests never hit the network.

⚠ **The suite runs in `<database>_test`, never in the development database.** It used to
share the dev database and scope its rows by test emails and "pytest" source prefixes. That
held while the dev database was nearly empty, and failed three separate ways once it held a
real life: seeded instruments collided with fixtures, real traces aged past the retention
limit and were counted by a retention test, and — the one that forced this — the first real
price feed gave HDFCBANK a close from yesterday, so eighteen tests that price a fictional
book on real symbols saw a real price instead of their own. Every one of those was a test
correctly assuming it controlled its own data. Now it does.

The scoping below is kept: it is what keeps one test from seeing another's rows.
"""

# ruff: noqa: E402 - the test database must be chosen before any app module creates an engine

# --- a database of its own. Must run before anything imports app.db.session. ---------------
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, make_url
from sqlalchemy import text as _sql

from app.config import settings

_dev_url = make_url(settings.database_url)
if not (_dev_url.database or "").endswith("_test"):
    _test_url = _dev_url.set(database=f"{_dev_url.database}_test")
    settings.database_url = _test_url.render_as_string(hide_password=False)

    _admin = create_engine(_dev_url, isolation_level="AUTOCOMMIT")
    with _admin.connect() as conn:
        exists = conn.execute(
            _sql("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": _test_url.database}
        ).first()
        if not exists:
            conn.execute(_sql(f'CREATE DATABASE "{_test_url.database}"'))
    _admin.dispose()

# Migrated in a subprocess on every run (a no-op when already at head): alembic's env.py
# calls logging.fileConfig, which would disable every logger already created in this process.
_backend = Path(__file__).resolve().parents[1]
subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    cwd=_backend,
    env={**os.environ, "DATABASE_URL": settings.database_url},
    check=True,
    capture_output=True,
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy import update as sa_update

from app.core.security import hash_password
from app.db.models import (
    AbMapping,
    ChatSession,
    CorporateAction,
    DailyUsage,
    FrameworkVersion,
    Fundamental,
    FxObservation,
    GeneratedReview,
    Instrument,
    JobRun,
    JournalEntry,
    Message,
    Notification,
    Portfolio,
    PriceObservation,
    ProfileFact,
    PushSubscription,
    SourceItem,
    Span,
    Task,
    Transaction,
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

#: Observations written by a test. Neither `price_observations` nor `fx_observations` has a
#: user column, and since `make_instrument` shares instrument rows with the real book they
#: cannot be scoped by orphanhood either. So the marker lives in `source`: **any test writing
#: a price or an FX rate MUST use a source starting with "pytest"**, or the row survives
#: teardown and prices somebody else's portfolio.
#:
#: ⚠ This is why `pricing.record`'s default of "USER" is never right in a test. A leaked
#: observation does not fail where it was written — it fails in an unrelated test two files
#: later, on a primary-key collision nobody connects to the real cause.
FX_TEST_SOURCE = "pytest"
TEST_SOURCE = FX_TEST_SOURCE

PRICE_TEST_SOURCE_MATCH = PriceObservation.source.like(f"{TEST_SOURCE}%")


def make_instrument(db, *, symbol, exchange, name, asset_class, currency, **extra):
    """Get-or-create an instrument, for test fixtures.

    ⚠ Get-or-create rather than a plain insert, because `instruments` has no user column and
    therefore no way to scope one test's instruments from another's — or from the REAL book.
    Seeding the development database with the actual portfolio (which is the only way to look
    at the Investments page with data in it) then made every fixture using a real symbol fail
    on `instruments_unique_live`, and the failure appeared as ninety-odd unrelated errors.

    A test suite that only passes when the developer's database is empty of real data is a
    suite that will be switched off. Positions are folded per PORTFOLIO, so sharing an
    instrument row with the real book changes no assertion.
    """
    import uuid as _uuid

    from app.db.models import Instrument as _Instrument

    existing = db.execute(
        select(_Instrument).where(
            _Instrument.symbol == symbol,
            _Instrument.exchange == exchange,
            _Instrument.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    inst = _Instrument(
        id=_uuid.uuid4(),
        symbol=symbol,
        exchange=exchange,
        name=name,
        asset_class=asset_class,
        currency=currency,
        **extra,
    )
    db.add(inst)
    return inst


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
        # The investment ledger is APPEND-ONLY, enforced by a database trigger, so an
        # ordinary DELETE raises. Test teardown is the one legitimate exception to that
        # rule, and it is made explicit here rather than by weakening the trigger: the
        # guarantee that matters is that *application code* cannot rewrite the record.
        #
        # Scoped to this user's books, like every other delete in this function — a
        # TRUNCATE would destroy real ledger rows on a shared development database.
        book_ids = [
            b.id for b in db.execute(select(Portfolio).where(Portfolio.user_id == u.id)).scalars()
        ]
        if book_ids:
            # Corporate actions point at the transaction they wrote, so they must go before
            # it. Scoped to instruments this user's books touched, like everything else here.
            db.execute(
                delete(CorporateAction).where(
                    CorporateAction.instrument_id.in_(
                        select(Transaction.instrument_id).where(
                            Transaction.portfolio_id.in_(book_ids)
                        )
                    )
                )
            )
            db.execute(text("ALTER TABLE transactions DISABLE TRIGGER transactions_append_only"))
            try:
                # Corrections point at what they replace, so children must go first or the
                # self-referencing foreign key blocks the delete.
                db.execute(
                    delete(Transaction).where(
                        Transaction.portfolio_id.in_(book_ids),
                        Transaction.supersedes_id.isnot(None),
                    )
                )
                db.execute(delete(Transaction).where(Transaction.portfolio_id.in_(book_ids)))
            finally:
                db.execute(text("ALTER TABLE transactions ENABLE TRIGGER transactions_append_only"))
            db.execute(delete(Portfolio).where(Portfolio.user_id == u.id))

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
    # `instruments` and `price_observations` have no user column, so they cannot be scoped by
    # test email. They are scoped by being ORPHANED instead: a real holding always has
    # transactions behind it, so an instrument with none is a leftover.
    #
    # ⚠ Order matters, and getting it wrong is subtle. Prices must go FIRST: an instrument
    # that still has a price observation is not orphaned, so it would survive teardown and
    # then collide with the next test on `instruments_unique_live` — which is exactly what
    # happened, and the failure appeared two tests later in an unrelated fixture.
    #
    # `price_observations` is append-only like `transactions`, so its trigger is lifted the
    # same way and for the same reason: the guarantee that matters is that application code
    # cannot rewrite the record.
    #
    # ⚠ Guarded by a cheap EXISTS check. `ALTER TABLE ... DISABLE TRIGGER` takes an ACCESS
    # EXCLUSIVE lock, and this purge runs twice for every test in the suite — issuing that
    # DDL unconditionally took the full run from 2.5 minutes to over ten. Almost no test
    # touches the ledger, so the common path must not pay for the rare one.
    # The framework, and where each company sits in it.
    #
    # ⚠ Unscoped, unlike almost everything above, and for a stated reason: neither table has a
    # user column and neither can be keyed to a test. They are safe to clear wholesale only
    # because the suite runs against its OWN database — the same licence the FX purge takes.
    # A mapping points at an instrument, so it must go before the orphan sweep below, and a
    # mapping points at a version, so versions go after.
    #
    # `superseded_by_id` is nulled first: the column references this same table, so deleting
    # every row in one statement can trip its own foreign key depending on the order Postgres
    # reaches them.
    # Filed figures and the documents they came from. ⚠ Both are append-only with a trigger,
    # so teardown lifts it exactly as it does for transactions — the guarantee that matters is
    # that APPLICATION code cannot rewrite the record, not that a test cannot clean up.
    # Figures reference documents, so they go first.
    if db.execute(select(SourceItem.id).limit(1)).first() is not None:
        for table in ("fundamentals", "source_items"):
            db.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {table}_append_only"))
        try:
            db.execute(delete(Fundamental))
            db.execute(delete(SourceItem))
        finally:
            for table in ("fundamentals", "source_items"):
                db.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {table}_append_only"))

    db.execute(sa_update(AbMapping).values(superseded_by_id=None))
    db.execute(delete(AbMapping))
    db.execute(delete(FrameworkVersion))

    orphaned = ~Instrument.id.in_(select(Transaction.instrument_id))
    if db.execute(select(Instrument.id).where(orphaned).limit(1)).first() is not None:
        db.execute(
            delete(CorporateAction).where(
                CorporateAction.instrument_id.in_(select(Instrument.id).where(orphaned))
            )
        )
        db.execute(
            text("ALTER TABLE price_observations DISABLE TRIGGER price_observations_append_only")
        )
        try:
            db.execute(
                delete(PriceObservation).where(
                    PriceObservation.instrument_id.in_(select(Instrument.id).where(orphaned))
                )
            )
        finally:
            db.execute(
                text("ALTER TABLE price_observations ENABLE TRIGGER price_observations_append_only")
            )
        db.execute(delete(Instrument).where(orphaned))

    # Prices a test wrote on an instrument SHARED with the real book. Those instruments are
    # not orphaned, so the sweep above never reaches them, and the row would collide on
    # `price_observations_pkey` the next time a test recorded the same instant.
    if (
        db.execute(
            select(PriceObservation.instrument_id).where(PRICE_TEST_SOURCE_MATCH).limit(1)
        ).first()
        is not None
    ):
        db.execute(
            text("ALTER TABLE price_observations DISABLE TRIGGER price_observations_append_only")
        )
        try:
            db.execute(delete(PriceObservation).where(PRICE_TEST_SOURCE_MATCH))
        finally:
            db.execute(
                text("ALTER TABLE price_observations ENABLE TRIGGER price_observations_append_only")
            )

    # `fx_observations` has neither a user nor an instrument to scope by — its key is
    # (pair, observed_at, source). So tests mark their rows in `source` and only those are
    # removed, the same way `job_runs` is scoped by TEST_PREFIX.
    #
    # ⚠ This was missing until a rate written by one test turned up inside another test's
    # portfolio curve, valuing a holding nobody had priced. Nothing had ever written an FX
    # observation before, so the gap was invisible rather than absent — which is the usual
    # shape of a teardown bug.
    #
    # Since the suite moved to a database of its own, every rate in it is a test's: the market
    # data tests write under real source names ("TWELVE_DATA"), so all rows go, not only
    # "pytest"-marked ones.
    if db.execute(select(FxObservation.pair).limit(1)).first() is not None:
        db.execute(text("ALTER TABLE fx_observations DISABLE TRIGGER fx_observations_append_only"))
        try:
            db.execute(delete(FxObservation))
        finally:
            db.execute(
                text("ALTER TABLE fx_observations ENABLE TRIGGER fx_observations_append_only")
            )
    db.commit()


@pytest.fixture(autouse=True)
def no_market_data_network(monkeypatch):
    """⚠ No test reaches a real price source.

    The developer's `.env` holds live market-data keys, and the portfolio tools refresh stale
    prices before answering — so without this, a tool test would log in to Angel One and
    spend Twelve Data's daily allowance. The keys are blanked, and any HTTP client the market
    data code builds fails instantly unless a test hands it a mock transport of its own.
    """
    import httpx

    from app.services.marketdata import angel_one
    from app.services.marketdata import http as md_http

    for key in (
        "angel_one_api_key",
        "angel_one_client_code",
        "angel_one_mpin",
        "angel_one_totp_secret",
        "coingecko_api_key",
        "twelve_data_api_key",
    ):
        monkeypatch.setattr(settings, key, "")

    def refuse(request):
        raise httpx.ConnectError("tests do not reach real price sources", request=request)

    monkeypatch.setattr(
        md_http, "client", lambda: httpx.Client(transport=httpx.MockTransport(refuse))
    )
    monkeypatch.setattr(md_http, "BACKOFF", (0.0, 0.0))
    monkeypatch.setattr(md_http, "_down_until", {})
    angel_one.reset_session()
    yield
    angel_one.reset_session()


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
