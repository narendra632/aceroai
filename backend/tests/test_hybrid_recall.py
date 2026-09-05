"""Hybrid recall: two rankers, fused by rank.

These tests assert **measured behaviour, not mechanism**. The point of the change is that
`"write a python function to reverse a list"` stops recalling twelve facts about the user's
family, and that `"where do I work"` puts the job first. Testing that RRF was called would
pass on an implementation that got both of those wrong.

Vectors are deterministic fakes so distances are exact and assertable; the *lexical* side
runs against real Postgres full-text search, because that is the half the change is about.
"""

import pytest
from sqlalchemy import select

from app.config import settings
from app.core import recall as hybrid
from app.db.models import ProfileFact
from app.services import memory as memory_service

# Filler facts sharing ordinary vocabulary, so document frequencies behave like a real
# memory rather than like a five-row fixture where every word is 20% of the corpus.
FILLER = [
    "Narendra prefers the morning slot for meetings.",
    "Narendra keeps a running note of ideas.",
    "Narendra drinks coffee before noon.",
    "Narendra listens to podcasts while commuting.",
    "Narendra reviews his notes on Sunday.",
    "Narendra uses a mechanical keyboard.",
    "Narendra dislikes long phone calls.",
    "Narendra takes the stairs when he can.",
    "Narendra plans his week on Monday.",
    "Narendra keeps his inbox at zero.",
    "Narendra prefers dark mode everywhere.",
    "Narendra reads before sleeping.",
    "Narendra tracks his spending monthly.",
    "Narendra avoids meetings after six.",
    "Narendra prefers tea in the evening.",
    "Narendra writes his own summaries.",
    "Narendra keeps a spare charger in his bag.",
    "Narendra prefers window seats.",
    "Narendra waters his plants on Saturday.",
    "Narendra backs up his laptop weekly.",
]


def _vec(spread: float) -> list[float]:
    """A vector whose cosine distance from `_vec(0)` grows with `spread`.

    distance = 1 - 1/sqrt(1 + spread^2), so 0 -> 0.000, 1 -> 0.293, 2 -> 0.553, 9 -> 0.890.
    That straddles the 0.52 vector-only floor on both sides, which is what the selection
    rule turns on.
    """
    v = [0.0] * settings.embed_dim
    v[0] = 1.0
    v[1] = float(spread)
    return v


def _unrelated() -> list[float]:
    """A query vector orthogonal to every fact vector above — cosine distance exactly 1.0.

    Needed because `_vec(large)` is NOT far from `_vec(1)`: both lean on the same first
    dimension, so [1, 9] sits 0.219 from [1, 1]. That is the trap the vector-only floor
    exists to catch, and a test using it would have measured nothing.
    """
    v = [0.0] * settings.embed_dim
    v[5] = 1.0
    return v


def _add(db, user, text, spread, *, status="active", deleted=False, category="other"):
    import datetime as dt

    row = ProfileFact(
        user_id=user.id,
        fact=text,
        category=category,
        confidence=0.9,
        source="inferred",
        status=status,
        embedding=_vec(spread),
        deleted_at=dt.datetime.now(dt.UTC) if deleted else None,
    )
    db.add(row)
    return row


@pytest.fixture
def memory(db, user):
    """A realistic little memory: twenty ordinary facts, plus the five this suite asks about.

    ⚠ The filler spreads must not COINCIDE with the spreads of the facts this suite asserts
    about. They did: `1 + (i % 3) * 0.05` produced 1.00, 1.05 and 1.10, and 1.10 is exactly
    the spread of both certification facts — so seven filler facts sat at an identical
    cosine distance to them, and which ones survived `LIMIT recall_pool` was decided by
    physical row order. That is what made five tests in this area fail at random in CI,
    always losing an early-inserted row, for weeks.

    The production code no longer breaks such ties arbitrarily (see `recall.vector_rank`),
    but a test whose subject is tied with its own filler is asserting something the data
    does not determine, whatever the tiebreak rule is. 0.03 keeps the fillers realistically
    nearby — 1.00, 1.03, 1.06 — while colliding with none of 1.1, 1.2, 1.3.
    """
    for i, text in enumerate(FILLER):
        _add(db, user, text, 1 + (i % 3) * 0.03)
    _add(db, user, "Narendra works at TCS.", 0, category="work")
    _add(db, user, "Narendra has completed the AI-901 certification.", 1.1, category="work")
    _add(db, user, "Narendra has completed the AI-103 certification.", 1.1, category="work")
    _add(db, user, "Narendra goes to the gym on weekday mornings.", 1.2, category="health")
    _add(db, user, "Narendra has two sisters.", 1.3, category="relationship")
    db.commit()
    return user


def _texts(facts):
    return [f.fact for f in facts]


def test_a_coding_question_recalls_nothing_by_meaning(db, memory):
    """The measurement that started this: recall used to return `MEMORY_RECALL_K` facts for
    every message, including one with no personal content at all.

    The honest claim is about the *meaning* ranker: nothing here is about the user, so it
    contributes nothing. A stray keyword can still land — English stemming maps `write` in
    "write a python function" onto "Narendra **writes** his own summaries" — and that is the
    accepted cost of the lexical lane, bounded at `lexical_only_max` and never presented as
    agreement. Twelve facts on every message is the failure this replaced; one bounded
    keyword hit is not.
    """
    facts = hybrid.search(db, memory, "write a python function to reverse a list", _unrelated())
    assert not [f for f in facts if f.via in (hybrid.BOTH, hybrid.VECTOR)]
    assert len(facts) <= settings.lexical_only_max


def test_a_question_sharing_no_vocabulary_recalls_nothing_at_all(db, memory):
    facts = hybrid.search(db, memory, "explain quaternion interpolation", _unrelated())
    assert facts == []


def test_a_distant_fact_is_never_reported_as_agreement(db, user):
    """A keyword hit on a fact the vector ranker put as far away as possible is not
    consensus, however the two pools happen to overlap.

    Found by this suite, not by reasoning: the vector ranker returns its 20 nearest rows
    whether or not any of them relate to the message, so on a small memory its pool is
    almost everything and "in both pools" stopped meaning anything. The popover would have
    told the user both rankers agreed on a fact sitting at distance 1.0.
    """
    _add(db, user, "Narendra keeps a running list of ideas.", 0)
    db.commit()

    facts = hybrid.search(db, user, "reverse a list in python", _unrelated())
    assert all(f.via != hybrid.BOTH for f in facts)


def test_the_job_question_puts_the_job_first(db, memory):
    facts = hybrid.search(db, memory, "where do I work", _vec(0))
    assert facts[0].fact == "Narendra works at TCS."
    # Found by BOTH rankers: the vector says "about this person", the word "work" says
    # "this one". Agreement is the signal the raw distance could not provide.
    assert facts[0].via == hybrid.BOTH


def test_both_certifications_come_back(db, memory):
    facts = _texts(hybrid.search(db, memory, "which certifications do I have", _vec(0)))
    assert "Narendra has completed the AI-901 certification." in facts
    assert "Narendra has completed the AI-103 certification." in facts


def test_recall_is_a_ceiling_not_a_quota(db, memory):
    """25 facts are stored and the limit is 16, yet an ordinary question returns far fewer.
    A quota would fill the space with whatever was least irrelevant."""
    facts = hybrid.search(db, memory, "when do I go to the gym", _vec(0))
    assert 0 < len(facts) < settings.memory_recall_k
    assert "Narendra goes to the gym on weekday mornings." in _texts(facts)


# --- lexical-only admission (the rule added after walking through a long message) ----


def test_a_rare_word_recalls_a_fact_the_vector_ranker_missed(db, user):
    """The case that changed the selection rule.

    A long, multi-topic message blurs into a vector that sits near nothing in particular,
    so a fact it names outright can fall outside the vector pool entirely. A hit on a rare
    word is stronger evidence than a mid-band distance, so it is admitted on its own.
    """
    for i, text in enumerate(FILLER):
        _add(db, user, text, 1 + (i % 3) * 0.05)  # all comfortably inside the vector pool
    _add(db, user, "Narendra has a dentist appointment on the fourth.", 9)  # d = 0.890
    db.commit()

    vector_only = hybrid.vector_rank(db, user.id, _vec(0), settings.recall_pool)
    assert "dentist" not in " ".join(f.fact for f, _ in vector_only)  # outside the pool

    facts = hybrid.search(db, user, "when is my dentist appointment", _vec(0))
    dentist = [f for f in facts if "dentist" in f.fact]
    assert dentist, "a rare word must be able to recall a fact on its own"
    assert dentist[0].via == hybrid.LEXICAL


def test_an_ordinary_shared_word_does_not_admit_a_fact_on_its_own(db, user):
    """The gate on that rule. `prefers` is spread across the memory, so it identifies
    nothing — a lexical-only slot filled by it would be noise."""
    for i in range(12):
        _add(db, user, f"Narendra prefers option number {i} in that situation.", 9)  # far
    for i, text in enumerate(FILLER[:12]):
        _add(db, user, text, 1 + (i % 3) * 0.05)
    db.commit()

    facts = hybrid.search(db, user, "what does he prefer", _vec(0))
    assert not [f for f in facts if f.via == hybrid.LEXICAL], (
        "a word common across memory must not admit a fact by itself"
    )


def test_a_word_in_almost_every_fact_is_dropped_entirely(db, memory):
    """Every fact begins with the user's name by design, so this is a real query shape.
    Left in, it matches the whole table and makes ranking cost linear in memory size."""
    words, _ = hybrid.choose_terms(db, memory.id, "what do you know about Narendra")
    assert "narendra" not in words


def test_long_messages_keep_the_rarest_words_not_the_first_ones(db, memory):
    message = (
        "I have been thinking about the week and the meetings and the notes and the plans "
        "and the ideas and the list and the summaries, but really what matters is the "
        "AI-901 certification."
    )
    words, rare = hybrid.choose_terms(db, memory.id, message)
    assert len(words) <= settings.lexical_terms_max
    # The identifying term survived the trim. Kept whole: Postgres splits `ai-901` into
    # `ai-901 & ai & 901` itself, so the hyphen costs nothing and losing it would.
    assert "ai-901" in words
    assert rare, "at least one term must be rare enough to carry a fact on its own"


# --- the guarantees that must not regress -------------------------------------------


def test_inactive_and_forgotten_facts_are_invisible_to_both_rankers(db, user):
    """A new retrieval path is a new place to leak a deleted record."""
    _add(db, user, "Narendra owns a xylophone.", 0, status="superseded")
    _add(db, user, "Narendra owns a harpsichord.", 0, status="rejected")
    _add(db, user, "Narendra owns a theremin.", 0, deleted=True)
    _add(db, user, "Narendra owns a guitar.", 0)
    db.commit()

    for query in ("xylophone", "harpsichord", "theremin"):
        assert hybrid.lexical_rank(db, user.id, [query], {query}, 20) == []
        assert query not in " ".join(_texts(hybrid.search(db, user, f"my {query}", _vec(0))))

    assert "Narendra owns a guitar." in _texts(hybrid.search(db, user, "my guitar", _vec(0)))


def test_one_ranker_failing_degrades_to_the_other(db, memory, monkeypatch):
    """Recall is best-effort. Fewer facts is a worse answer; an exception is a broken chat."""

    def boom(*a, **kw):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(hybrid, "lexical_rank", boom)
    assert hybrid.search(db, memory, "where do I work", _vec(0)), "vector must carry on alone"

    monkeypatch.undo()
    monkeypatch.setattr(hybrid, "vector_rank", boom)
    assert hybrid.search(db, memory, "certification", _vec(0)), "lexical must carry on alone"


def test_an_empty_lexical_result_is_an_answer_not_a_failure(db, memory):
    """Finding nothing and raising are different. If they were conflated, the python
    question would fall back to the old behaviour and return twelve facts again."""
    words, _ = hybrid.choose_terms(db, memory.id, "xylophone harpsichord theremin")
    assert words == []
    assert hybrid.search(db, memory, "xylophone harpsichord theremin", _unrelated()) == []


# --- tied distances -------------------------------------------------------------------
#
# Two facts can sit at EXACTLY the same cosine distance from a query. `ORDER BY distance
# LIMIT n` then returns whichever ones Postgres scanned first, and that order changes as
# the heap is rewritten — so identical data could answer the same question differently on
# consecutive calls. It did, undetected, for as long as recall has existed. These tests pin
# the total ordering that replaced it.


def test_tied_facts_are_ranked_newest_first(db, user):
    """When meaning cannot separate two facts, recency does — and it does so every time.

    Written against the actual defect: five facts with IDENTICAL vectors, a limit of two.
    Without a tiebreak the two returned were whichever the scan reached first, which is
    insertion order — the two OLDEST. The rule is the opposite, and it is a rule rather
    than an accident.
    """
    import datetime as dt

    base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    for n in range(5):
        row = _add(db, user, f"Narendra tied fact number {n}.", 1.0)
        row.created_at = base + dt.timedelta(days=n)
    db.commit()

    ranked = hybrid.vector_rank(db, user.id, _vec(1.0), 2)
    assert [f.fact for f, _ in ranked] == [
        "Narendra tied fact number 4.",
        "Narendra tied fact number 3.",
    ]
    assert ranked[0][1] == ranked[1][1], "the premise: these really are tied"


def test_tied_ranking_survives_the_heap_being_rewritten(db, user):
    """The same question, the same data, the same answer — after the rows have moved.

    ⚠ Honest about its own strength: this one **passed even without the tiebreak**, so it is
    a guard rather than a reproduction. Postgres updates a row in place when the page has
    space, so a single pass of small updates does not reliably disturb the scan order — what
    does is months of ordinary use and autovacuum, which a test cannot stage.

    `test_tied_facts_are_ranked_newest_first` and `test_the_nearest_active_fact_is_not_a_coin_flip`
    are the two that actually fail without the fix; both were confirmed red against the old
    ordering before this was committed. This test is kept because the invariant it states —
    identical data answers identically — is the one that matters in production, and it will
    catch a future change that reintroduces a partial order by some other route.
    """
    for n in range(6):
        _add(db, user, f"Narendra shuffled fact number {n}.", 1.0)
    db.commit()

    before = [f.fact for f, _ in hybrid.vector_rank(db, user.id, _vec(1.0), 3)]

    for row in db.execute(select(ProfileFact).where(ProfileFact.user_id == user.id)).scalars():
        row.confidence = 0.5  # a real UPDATE: same values ranked, new physical order
    db.commit()

    after = [f.fact for f, _ in hybrid.vector_rank(db, user.id, _vec(1.0), 3)]
    assert before == after


def test_the_nearest_active_fact_is_not_a_coin_flip(db, user):
    """Contradiction detection asks for ONE nearest fact. A tie made that arbitrary.

    This is the higher-stakes half of the same defect: `nearest_active` decides which
    existing fact a new one is judged against, so an arbitrary winner means a new fact is
    compared with an arbitrary member of a tied group.
    """
    import datetime as dt

    base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    for n in range(4):
        row = _add(db, user, f"Narendra equidistant fact number {n}.", 1.0)
        row.created_at = base + dt.timedelta(days=n)
    db.commit()

    for _ in range(3):
        found = memory_service.nearest_active(db, user.id, _vec(1.0))
        assert found is not None
        assert found[0].fact == "Narendra equidistant fact number 3."
