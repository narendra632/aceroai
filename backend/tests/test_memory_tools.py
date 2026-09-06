"""The assistant writing to memory deliberately, and the one writer both paths share.

Named for the bug. This exchange happened on the live app:

    user: remember that I have the AI-901 certification
    assistant: Got it, I've stored that.        <- nothing was stored
    user: do I have AI-901?
    assistant: I don't have that in my memory.

Two defects: no tool could write memory, and the model could narrate a write it never made.
Both are asserted below.
"""

import asyncio

import pytest
from sqlalchemy import select

from app.config import settings
from app.core import memory as core_memory
from app.core import tools
from app.db.models import ProfileFact
from app.services import memory as svc
from tests._quarantine import MEMORY_VISIBILITY_RACE


def _vec(i: int, val: float = 1.0) -> list[float]:
    v = [0.0] * settings.embed_dim
    v[i] = val
    return v


@pytest.fixture
def embed(monkeypatch):
    """Hand out a distinct vector per call so stored facts are far apart unless a test
    deliberately makes them close."""
    state = {"n": 20}

    def use(*vectors):
        queue = list(vectors)

        async def fake(texts, usage=None):
            out = []
            for _ in texts:
                if queue:
                    out.append(queue.pop(0))
                else:
                    state["n"] += 1
                    out.append(_vec(state["n"]))
            return out

        monkeypatch.setattr("app.core.llm.embed", fake)

    use()
    return use


def _run(name, db, user, args):
    return asyncio.run(tools.execute(db, user.id, name, args))


def _facts(db, user, status="active"):
    return (
        db.execute(
            select(ProfileFact).where(
                ProfileFact.user_id == user.id,
                ProfileFact.status == status,
                ProfileFact.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )


# --- the exchange that failed -------------------------------------------------------


@MEMORY_VISIBILITY_RACE
def test_remember_fact_stores_something_recallable(db, user, embed):
    """3.7 — the exact instruction that used to do nothing."""
    result = _run(
        "remember_fact",
        db,
        user,
        {"fact": "Narendra has completed the AI-901 certification.", "category": "work"},
    )

    assert result["ok"] is True
    assert result["result"]["action"] == svc.STORED
    row = db.get(ProfileFact, result["result"]["id"])
    assert row.fact == "Narendra has completed the AI-901 certification."
    # A fact the user stated is not an inference, and it must carry a vector or it would
    # show on the Knowledge page while never informing another conversation.
    assert row.source == "stated"
    assert row.embedding is not None
    assert "AI-901" in " ".join(core_memory.recall_facts(db, user, row.embedding, k=5))


def test_a_failed_write_is_reported_as_a_failure(db, user, embed):
    """3.8 — the defect that let 'Got it, I've stored that' stand over an empty memory."""
    result = _run("correct_fact", db, user, {"fact_id": "not-a-uuid", "new_fact": "anything"})
    assert result["ok"] is False
    assert "error" in result
    assert "result" not in result

    missing = _run("forget_fact", db, user, {"fact_id": "00000000-0000-0000-0000-000000000000"})
    assert missing["ok"] is False


def test_two_certifications_differing_only_by_code_both_survive(db, user, embed):
    """2.4 — the regression test this whole change exists for.

    Measured on the live embedding model, these two sentences are **0.098** apart, inside
    the 0.12 dedup threshold. The second used to be deleted on the way in.
    """
    close, closer = _vec(1), _vec(1, 0.995)  # ~0.005 apart: well inside the threshold
    embed(close, closer)

    first = _run("remember_fact", db, user, {"fact": "Narendra has the AI-901 certification."})
    second = _run("remember_fact", db, user, {"fact": "Narendra has the AI-103 certification."})

    assert first["result"]["action"] == svc.STORED
    assert second["result"]["action"] == svc.FLAGGED  # stored, and the doubt is recorded
    stored = {f.fact for f in _facts(db, user)}
    assert stored == {
        "Narendra has the AI-901 certification.",
        "Narendra has the AI-103 certification.",
    }
    # The doubt is visible and answerable rather than resolved by deletion.
    assert second["result"]["resembles"]["id"] == first["result"]["id"]


def test_a_suspected_duplicate_can_be_dismissed(db, user, embed):
    embed(_vec(1), _vec(1, 0.995))
    _run("remember_fact", db, user, {"fact": "Narendra has the AI-901 certification."})
    second = _run("remember_fact", db, user, {"fact": "Narendra has the AI-103 certification."})

    cleared = svc.clear_duplicate_flag(db, user.id, second["result"]["id"])
    assert cleared.possible_duplicate_of is None


# --- correcting and forgetting ------------------------------------------------------


def test_correcting_supersedes_rather_than_overwriting(db, user, embed):
    """2.5 — a genuine change keeps its history."""
    stored = _run("remember_fact", db, user, {"fact": "Narendra works at Infosys."})
    fact_id = stored["result"]["id"]

    result = _run(
        "correct_fact", db, user, {"fact_id": fact_id, "new_fact": "Narendra works at TCS."}
    )

    assert result["ok"] is True
    assert result["result"]["replaced"]["fact"] == "Narendra works at Infosys."
    old = db.get(ProfileFact, fact_id)
    assert old.status == "superseded"
    assert old.superseded_by is not None  # history preserved, not destroyed
    assert [f.fact for f in _facts(db, user)] == ["Narendra works at TCS."]


def test_forgetting_names_what_it_forgot(db, user, embed):
    """The reply has to be checkable. 'I've forgotten that' is not; naming it is."""
    stored = _run("remember_fact", db, user, {"fact": "Narendra prefers tea."})
    result = _run("forget_fact", db, user, {"fact_id": stored["result"]["id"]})

    assert result["result"]["fact"] == "Narendra prefers tea."
    assert _facts(db, user) == []
    # Soft delete: recall cannot reach it, and Restore still works.
    assert svc.restore_fact(db, user.id, stored["result"]["id"]).deleted_at is None


# --- one writer, two callers --------------------------------------------------------


def test_the_tool_and_the_extractor_write_identical_rows(db, user, embed):
    """1.6 — the guarantee that there is exactly one writer.

    Same text, same vector, two entry points. If these ever diverge, a fact learned in the
    background and a fact the user asked for by name are governed by different rules.
    """
    text = "Narendra plays the sitar."
    embed(_vec(30))
    _run("remember_fact", db, user, {"fact": text, "category": "preference"})
    from_tool = _facts(db, user)[0]

    other = svc.remember(
        db,
        user.id,
        text,
        category="preference",
        embedding=_vec(31),
        source="stated",
        confidence=1.0,
    ).fact

    for field in ("fact", "category", "source", "status", "confidence"):
        assert getattr(from_tool, field) == getattr(other, field)


def test_background_extraction_cannot_delete(db, user):
    """Decision 7. Extraction may add and supersede; deleting in an unattended loop with
    nobody watching is neither observed nor prompted."""
    assert "forget" not in core_memory._store.__code__.co_names
    exposed = set(svc.__dict__) & {"forget_fact"}
    assert exposed, "forget must still exist for the paths that DO have a human present"


# --- the registry -------------------------------------------------------------------


def test_every_schema_has_a_handler_and_every_handler_a_schema(db, user):
    """5.4 — a schema with no handler is a tool that always fails; a handler with no schema
    is dead code. Checked at import too, so this test documents the rule."""
    names = {t["function"]["name"] for t in tools.TOOLS}
    assert names == set(tools._DISPATCH)
    assert {"remember_fact", "correct_fact", "forget_fact"} <= names
    # A bare count is a deliberate tripwire: it catches a tool quietly disappearing, which
    # the set comparisons above would not. Broken down so the next person to add a domain
    # sees which number to change and why, rather than a naked integer.
    assert len(tools.TOOLS) == 16, {
        "tasks+journal": 7,
        "memory": 3,
        "investments": 6,
        "actual": sorted(t["function"]["name"] for t in tools.TOOLS),
    }


def test_an_unknown_tool_is_an_error_not_a_crash(db, user):
    assert _run("summon_a_demon", db, user, {})["ok"] is False
