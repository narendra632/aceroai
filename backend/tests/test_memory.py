"""Memory: semantic recall, embedded storage with dedup, background extraction,
and context injection. Uses the real Postgres (pgvector) with deterministic fake
embeddings so vector ordering is assertable without a live provider.
"""

import asyncio
import uuid

from sqlalchemy import func, select

from app.config import settings
from app.core import composer, memory
from app.core.recall import RecalledFact
from app.db.models import ChatSession, ProfileFact


def _onehot(i: int, val: float = 1.0) -> list[float]:
    v = [0.0] * settings.embed_dim
    v[i] = val
    return v


def _fact(user, text, vec, *, status="active", category="preference"):
    return ProfileFact(
        user_id=user.id,
        fact=text,
        category=category,
        confidence=0.9,
        source="inferred",
        status=status,
        embedding=vec,
    )


def _active_count(db, user) -> int:
    return db.execute(
        select(func.count())
        .select_from(ProfileFact)
        .where(ProfileFact.user_id == user.id, ProfileFact.status == "active")
    ).scalar()


def test_recall_orders_by_similarity_and_excludes_inactive(db, user):
    db.add_all(
        [
            _fact(user, "likes tea", _onehot(0)),
            _fact(user, "works in finance", _onehot(1), category="work"),
            _fact(user, "lives in Pune", _onehot(2), category="other"),
            _fact(user, "old tea note", _onehot(0), status="superseded"),
        ]
    )
    db.commit()

    facts = memory.recall_facts(db, user, _onehot(0), k=2)

    assert facts[0] == "likes tea"  # closest to the query vector
    assert "old tea note" not in facts  # superseded never recalled
    assert len(facts) <= 2


def test_recall_k_zero_returns_nothing(db, user):
    db.add(_fact(user, "likes tea", _onehot(0)))
    db.commit()
    assert memory.recall_facts(db, user, _onehot(0), k=0) == []


def test_store_flags_a_near_duplicate_instead_of_dropping_it(db, user):
    """The behaviour change this whole spec exists for.

    A proposed fact that sits close to an existing one used to be DELETED. It is now
    stored and linked to its suspected twin, because cosine distance measures subject
    matter and not identity — see the AI-901 regression test below.
    """
    original = _fact(user, "likes tea", _onehot(5))
    db.add(original)
    db.commit()
    db.refresh(original)

    counts = memory._store(
        user.id, [{"fact": "enjoys tea", "category": "preference", "confidence": 0.8}], [_onehot(5)]
    )

    assert counts == {"stored": 0, "superseded": 0, "flagged": 1, "unchanged": 0}
    assert _active_count(db, user) == 2  # stored, NOT discarded
    stored = db.execute(
        select(ProfileFact).where(ProfileFact.user_id == user.id, ProfileFact.fact == "enjoys tea")
    ).scalar_one()
    assert stored.possible_duplicate_of == original.id


def test_store_inserts_new_fact_with_embedding(db, user):
    counts = memory._store(
        user.id,
        [{"fact": "plays guitar", "category": "preference", "confidence": 0.8}],
        [_onehot(10)],
    )

    assert counts == {"stored": 1, "superseded": 0, "flagged": 0, "unchanged": 0}
    row = db.execute(select(ProfileFact).where(ProfileFact.user_id == user.id)).scalars().first()
    assert row.fact == "plays guitar"
    assert row.source == "inferred"
    assert row.status == "active"
    assert row.embedding is not None


def test_extract_and_store_persists_extracted_facts(monkeypatch, db, user):
    async def fake_complete(messages, model=None, effort=None, provider=None, usage=None):
        return '[{"fact": "User loves hiking", "category": "preference", "confidence": 0.9}]'

    monkeypatch.setattr("app.core.llm.complete", fake_complete)

    asyncio.run(memory.extract_and_store(user.id, "I love hiking", "Nice!"))

    facts = (
        db.execute(select(ProfileFact.fact).where(ProfileFact.user_id == user.id)).scalars().all()
    )
    assert "User loves hiking" in facts


def test_extract_and_store_swallows_errors(monkeypatch, db, user):
    async def boom(messages, model=None, effort=None, provider=None, usage=None):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.core.llm.complete", boom)

    # Must not raise — the reply was already delivered.
    asyncio.run(memory.extract_and_store(user.id, "hi", "hello"))

    assert _active_count(db, user) == 0


def test_extract_ignores_empty_extraction(monkeypatch, db, user):
    async def empty(messages, model=None, effort=None, provider=None, usage=None):
        return "[]"

    monkeypatch.setattr("app.core.llm.complete", empty)
    asyncio.run(memory.extract_and_store(user.id, "small talk", "sure"))
    assert _active_count(db, user) == 0


def test_build_context_injects_facts_after_persona(db, user):
    session = ChatSession(user_id=user.id, channel="web", title="t")
    db.add(session)
    db.commit()
    db.refresh(session)

    recalled = RecalledFact(uuid.uuid4(), "User likes tea", "preference", "both")
    ctx = composer.build_context(db, session.id, facts=[recalled])
    assert ctx[0]["role"] == "system"  # persona
    assert ctx[1]["role"] == "system"  # current date/time
    assert ctx[2]["role"] == "system"  # facts block
    assert "User likes tea" in ctx[2]["content"]
    # The id travels with the fact, so correct_fact/forget_fact can act in one step.
    assert str(recalled.id) in ctx[2]["content"]


def test_build_context_omits_facts_when_none(db, user):
    session = ChatSession(user_id=user.id, channel="web", title="t")
    db.add(session)
    db.commit()
    db.refresh(session)

    ctx = composer.build_context(db, session.id, facts=None)
    assert len(ctx) == 2  # persona + current date/time; no messages, no facts block


def test_the_exact_same_sentence_is_not_stored_twice(db, user):
    """The one principled exception to store-don't-drop.

    Near-duplicates are kept because distance cannot tell a restatement from a change.
    Identical text carries no such ambiguity — every character is already stored, so there
    is nothing to lose. MEASURED live: without this, asking the assistant to remember
    something wrote the fact once via the tool and again via the background extractor
    reading the same turn, and recall then returned both copies.
    """
    first = memory._store(
        user.id,
        [{"fact": "Narendra plays the sitar.", "category": "preference", "confidence": 1.0}],
        [_onehot(11)],
    )
    assert first["stored"] == 1

    again = memory._store(
        user.id,
        # different spacing and case: the same sentence, as a language model would re-emit it
        [{"fact": "  narendra  plays the SITAR. ", "category": "preference", "confidence": 0.8}],
        [_onehot(12)],
    )
    assert again == {"stored": 0, "superseded": 0, "flagged": 0, "unchanged": 1}
    assert _active_count(db, user) == 1
