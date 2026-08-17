"""Contradiction handling, provenance, and the bounded extraction prompt.

The defect these cover: cosine distance cannot tell "said the same thing again" from
"this changed", because a fact that changed is worded almost identically to the one it
replaces. Before this, a changed fact was either silently discarded by the duplicate gate
or stored alongside its own contradiction with nothing marking which was current.
"""

import asyncio
import json

from sqlalchemy import select

from app.core import memory
from app.db.models import ProfileFact
from app.services import memory as svc


def _onehot(i: int, val: float = 1.0) -> list[float]:
    from app.config import settings

    v = [0.0] * settings.embed_dim
    v[i] = val
    return v


def _fact(user, text, vec, **kw):
    return ProfileFact(
        user_id=user.id,
        fact=text,
        category=kw.pop("category", "work"),
        confidence=kw.pop("confidence", 0.9),
        source=kw.pop("source", "inferred"),
        status=kw.pop("status", "active"),
        embedding=vec,
        **kw,
    )


def _extractor(payload):
    async def fake(messages, model=None, effort=None, provider=None):
        return json.dumps(payload)

    return fake


def _embedder(*vectors):
    """Pin what the extracted facts embed to.

    The default fake embedder derives a vector from the text, so two differently-worded
    facts are never close. To exercise the duplicate gate the new fact has to actually land
    on top of the stored one, which means saying so explicitly.
    """

    async def fake(texts):
        return list(vectors)

    return fake


# --- contradiction ----------------------------------------------------------------


def test_changed_fact_supersedes_instead_of_being_dropped(monkeypatch, db, user):
    """The core defect. The old and new facts sit at the SAME vector — indistinguishable
    to the duplicate gate — so without `replaces` the newer truth would be discarded."""
    old = _fact(user, "works at Company A", _onehot(3))
    db.add(old)
    db.commit()
    db.refresh(old)

    monkeypatch.setattr(
        "app.core.llm.complete",
        _extractor(
            [
                {
                    "fact": "works at Company B",
                    "category": "work",
                    "confidence": 0.9,
                    "replaces": "works at Company A",
                }
            ]
        ),
    )

    asyncio.run(
        memory.extract_and_store(
            user.id, "I moved to Company B", "Congratulations!", known=["works at Company A"]
        )
    )

    db.refresh(old)
    assert old.status == "superseded"
    assert old.superseded_by is not None

    live = [f.fact for f in svc.list_facts(db, user.id)]
    assert live == ["works at Company B"]

    # And the retired belief no longer reaches the model.
    assert "works at Company A" not in memory.recall_facts(db, user, _onehot(3), k=10)


def test_genuine_repeat_is_still_deduplicated(monkeypatch, db, user):
    """A restatement must NOT create a supersession chain — that would fill the history
    with events that never happened."""
    db.add(_fact(user, "likes tea", _onehot(5), category="preference"))
    db.commit()

    monkeypatch.setattr(
        "app.core.llm.complete",
        _extractor([{"fact": "enjoys tea", "category": "preference", "confidence": 0.8}]),
    )
    monkeypatch.setattr("app.core.llm.embed", _embedder(_onehot(5)))  # lands on the stored fact

    asyncio.run(memory.extract_and_store(user.id, "tea again", "noted", known=["likes tea"]))

    rows = db.execute(select(ProfileFact).where(ProfileFact.user_id == user.id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "active"
    assert rows[0].superseded_by is None


def test_unknown_replaces_target_is_ignored_not_guessed(monkeypatch, db, user):
    """If the model names a fact we can't find, store the new fact normally rather than
    guessing which existing one it meant. A wrong guess destroys a real belief."""
    db.add(_fact(user, "works at Company A", _onehot(3)))
    db.commit()

    monkeypatch.setattr(
        "app.core.llm.complete",
        _extractor(
            [
                {
                    "fact": "plays the sitar",
                    "category": "preference",
                    "confidence": 0.9,
                    "replaces": "a fact that does not exist",
                }
            ]
        ),
    )

    asyncio.run(memory.extract_and_store(user.id, "...", "...", known=["works at Company A"]))

    facts = {f.fact: f for f in svc.list_facts(db, user.id)}
    assert set(facts) == {"works at Company A", "plays the sitar"}
    assert facts["works at Company A"].status == "active"  # untouched


def test_replaces_match_tolerates_whitespace_and_case(monkeypatch, db, user):
    """The model echoes text back; demanding byte-identical output from an LLM would make
    this feature fail silently most of the time."""
    old = _fact(user, "Works at Company A", _onehot(3))
    db.add(old)
    db.commit()
    db.refresh(old)

    monkeypatch.setattr(
        "app.core.llm.complete",
        _extractor(
            [
                {
                    "fact": "works at Company B",
                    "category": "work",
                    "confidence": 0.9,
                    "replaces": "  works at   company a ",
                }
            ]
        ),
    )

    asyncio.run(memory.extract_and_store(user.id, "...", "...", known=["Works at Company A"]))

    db.refresh(old)
    assert old.status == "superseded"


# --- provenance -------------------------------------------------------------------


def test_extracted_fact_records_where_it_came_from(monkeypatch, db, user):
    import uuid as _uuid

    source = _uuid.uuid4()
    monkeypatch.setattr(
        "app.core.llm.complete",
        _extractor([{"fact": "runs marathons", "category": "health", "confidence": 0.9}]),
    )

    asyncio.run(
        memory.extract_and_store(user.id, "I run marathons", "Impressive!", source_ref=source)
    )

    row = db.execute(select(ProfileFact).where(ProfileFact.user_id == user.id)).scalars().one()
    assert row.source_ref == source


def test_chat_turn_threads_the_message_id_into_provenance(auth_client, db, user, monkeypatch):
    """End to end through the real handler: the fact must point at the message that
    produced it, not at nothing."""
    monkeypatch.setattr("app.config.settings.memory_extraction_enabled", True)
    monkeypatch.setattr(
        "app.core.llm.complete",
        _extractor(
            [{"fact": "collects vinyl records", "category": "preference", "confidence": 0.9}]
        ),
    )

    auth_client.post("/api/chat", json={"message": "I collect vinyl records"})

    # Extraction is a background task; give the loop a moment to finish it.
    for _ in range(50):
        row = (
            db.execute(select(ProfileFact).where(ProfileFact.user_id == user.id)).scalars().first()
        )
        if row is not None:
            break
        import time as _time

        _time.sleep(0.05)
        db.expire_all()

    assert row is not None, "extraction never stored the fact"
    assert row.source_ref is not None, "the originating message was not recorded"


# --- the bounded prompt -----------------------------------------------------------


def test_dedup_holds_even_when_the_known_block_is_empty(monkeypatch, db, user):
    """Decision 8's safety argument, asserted.

    The extractor is shown NOTHING, and still cannot create a duplicate — because the
    guarantee lives in the vector gate, not in the prompt. This is what makes bounding the
    known-facts list safe.
    """
    db.add(_fact(user, "likes tea", _onehot(5), category="preference"))
    db.commit()

    monkeypatch.setattr(
        "app.core.llm.complete",
        _extractor([{"fact": "enjoys tea", "category": "preference", "confidence": 0.8}]),
    )
    monkeypatch.setattr("app.core.llm.embed", _embedder(_onehot(5)))  # lands on the stored fact

    asyncio.run(memory.extract_and_store(user.id, "tea", "noted", known=[]))

    rows = db.execute(select(ProfileFact).where(ProfileFact.user_id == user.id)).scalars().all()
    assert len(rows) == 1  # no duplicate, despite the extractor knowing nothing


def test_extraction_prompt_contains_only_the_facts_it_was_given(monkeypatch, db, user):
    """The prompt must be sized by what recall returned, not by everything ever learned."""
    for i in range(30):
        db.add(_fact(user, f"stored fact number {i}", _onehot(100 + i)))
    db.commit()

    seen = {}

    async def capture(messages, model=None, effort=None, provider=None):
        seen["prompt"] = messages[-1]["content"]
        return "[]"

    monkeypatch.setattr("app.core.llm.complete", capture)

    asyncio.run(memory.extract_and_store(user.id, "hello", "hi", known=["stored fact number 0"]))

    assert "stored fact number 0" in seen["prompt"]
    assert "stored fact number 29" not in seen["prompt"]  # the other 29 never reach the model


def test_unbounded_loader_is_gone():
    """`_load_active_facts` selected every active fact with no limit. Leaving it in the
    module would be an invitation to call it again."""
    assert not hasattr(memory, "_load_active_facts")


# --- phrasing consistency ---------------------------------------------------------


def test_extractor_is_told_to_keep_the_subject_consistent():
    """Guards a rule that is invisible until it is missing.

    The subject of a sentence moves its embedding as much as the claim does. Measured:
    "The user works at Infosys" sits 0.328 from "Narendra works at TCS", while
    "Narendra works at Infosys" sits 0.131 from it — the same contradiction, 2.5x closer.
    Drifting between a name and a generic reference hides real conflicts, so if a future
    prompt rewrite drops this rule the damage would be silent and only visible months
    later as contradictions nothing detected.
    """
    prompt = memory._EXTRACT_SYSTEM.lower()
    assert "same way" in prompt
    assert "known facts" in prompt
    assert "the user" in prompt


def test_extraction_prompt_shows_the_known_facts_it_must_match(monkeypatch, db, user):
    """The 'match the known facts' rule only works if the known facts are actually in the
    prompt where the model can see their wording."""
    seen = {}

    async def capture(messages, model=None, effort=None, provider=None):
        seen["prompt"] = messages[-1]["content"]
        return "[]"

    monkeypatch.setattr("app.core.llm.complete", capture)
    asyncio.run(
        memory.extract_and_store(
            user.id, "hi", "hello", known=["Narendra works at TCS.", "Narendra has sisters."]
        )
    )

    assert "Narendra works at TCS." in seen["prompt"]
    assert "Narendra has sisters." in seen["prompt"]
