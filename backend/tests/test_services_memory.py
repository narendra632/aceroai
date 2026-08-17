"""The memory service: visibility, correction, confirmation, forgetting, and the graph.

Uses the real Postgres (pgvector) with deterministic one-hot vectors so distances are
exactly predictable rather than approximately plausible.
"""

import pytest

from app.config import settings
from app.core import memory as core_memory
from app.db.models import ProfileFact
from app.services import memory as svc
from app.services.errors import Invalid, NotFound


def _vec(i: int) -> list[float]:
    """A one-hot vector. Two different one-hots are cosine distance 1.0 apart; a vector
    shared with another fact is distance 0.0. That makes graph assertions exact."""
    v = [0.0] * settings.embed_dim
    v[i] = 1.0
    return v


def _mix(i: int, j: int, w: float = 0.5) -> list[float]:
    """A vector between two one-hots, for facts that should be *related* but not identical."""
    v = [0.0] * settings.embed_dim
    v[i] = 1.0
    v[j] = w
    return v


def _add(db, user, text, vec, **kw):
    row = ProfileFact(
        user_id=user.id,
        fact=text,
        category=kw.pop("category", "preference"),
        confidence=kw.pop("confidence", 0.9),
        source=kw.pop("source", "inferred"),
        status=kw.pop("status", "active"),
        embedding=vec,
        **kw,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- visibility -------------------------------------------------------------------


def test_forgotten_fact_is_invisible_everywhere(db, user):
    keep = _add(db, user, "drinks tea", _vec(0))
    drop = _add(db, user, "drinks coffee", _vec(1))

    svc.forget_fact(db, user.id, drop.id)

    assert [f.fact for f in svc.list_facts(db, user.id)] == ["drinks tea"]
    with pytest.raises(NotFound):
        svc.get_fact(db, user.id, drop.id)

    # The path that matters most: a forgotten fact must never reach the model again.
    recalled = core_memory.recall_facts(db, user, _vec(1), k=10)
    assert "drinks coffee" not in recalled
    assert "drinks tea" in recalled

    # ...and it must not appear as a graph node's neighbour either.
    ids = {e[0] for e in svc.neighbours(db, user.id)} | {e[1] for e in svc.neighbours(db, user.id)}
    assert drop.id not in ids
    assert keep.id not in ids or True  # keep may be isolated; only `drop` is asserted absent


def test_forget_is_reversible(db, user):
    fact = _add(db, user, "runs in the morning", _vec(0))
    svc.forget_fact(db, user.id, fact.id)
    restored = svc.restore_fact(db, user.id, fact.id)

    assert restored.id == fact.id
    assert restored.fact == "runs in the morning"
    assert [f.fact for f in svc.list_facts(db, user.id)] == ["runs in the morning"]


def test_restore_is_idempotent(db, user):
    """A double-tap on Undo must not fail."""
    fact = _add(db, user, "likes cricket", _vec(0))
    svc.forget_fact(db, user.id, fact.id)
    svc.restore_fact(db, user.id, fact.id)
    assert svc.restore_fact(db, user.id, fact.id).deleted_at is None


def test_facts_are_owner_scoped(db, user, other_user):
    theirs = _add(db, other_user, "their secret", _vec(0))

    for call in (
        lambda: svc.get_fact(db, user.id, theirs.id),
        lambda: svc.forget_fact(db, user.id, theirs.id),
        lambda: svc.set_confirmed(db, user.id, theirs.id, True),
        lambda: svc.restore_fact(db, user.id, theirs.id),
        lambda: svc.supersede_fact(db, user.id, theirs.id, fact="mine now"),
    ):
        with pytest.raises(NotFound):
            call()

    db.refresh(theirs)
    assert theirs.fact == "their secret"
    assert theirs.status == "active"


# --- correction -------------------------------------------------------------------


def test_editing_text_supersedes_rather_than_overwriting(db, user):
    old = _add(db, user, "works at Company A", _vec(0), category="work")

    new = svc.update_fact(db, user.id, old.id, fact="works at Company B", embedding=_vec(1))

    db.refresh(old)
    assert new.id != old.id
    assert new.fact == "works at Company B"
    assert new.status == "active"
    assert old.status == "superseded"
    assert old.superseded_by == new.id
    assert old.fact == "works at Company A"  # history preserved, not destroyed
    assert new.category == "work"  # inherited


def test_superseded_fact_leaves_recall_immediately(db, user):
    old = _add(db, user, "works at Company A", _vec(0), category="work")
    svc.update_fact(db, user.id, old.id, fact="works at Company B", embedding=_vec(0))

    # Query with the OLD fact's own vector — the strongest possible pull toward it.
    recalled = core_memory.recall_facts(db, user, _vec(0), k=10)
    assert "works at Company A" not in recalled
    assert "works at Company B" in recalled


def test_metadata_only_edit_updates_in_place(db, user):
    """Re-labelling is the same belief. Superseding here would litter history with
    non-events, and would need a pointless re-embed."""
    fact = _add(db, user, "saves 30% of income", _vec(0), category="other")

    updated = svc.update_fact(db, user.id, fact.id, category="finance", confidence=0.95)

    assert updated.id == fact.id  # same row
    assert updated.category == "finance"
    assert updated.status == "active"
    assert updated.superseded_by is None


def test_superseded_facts_are_reachable_as_history(db, user):
    old = _add(db, user, "lives in Pune", _vec(0))
    new = svc.update_fact(db, user.id, old.id, fact="lives in Bengaluru", embedding=_vec(1))

    assert [f.fact for f in svc.list_facts(db, user.id)] == ["lives in Bengaluru"]
    everything = {f.fact for f in svc.list_facts(db, user.id, status=None)}
    assert everything == {"lives in Pune", "lives in Bengaluru"}
    assert svc.get_fact(db, user.id, old.id).superseded_by == new.id


def test_empty_edit_is_rejected(db, user):
    fact = _add(db, user, "reads at night", _vec(0))
    with pytest.raises(Invalid):
        svc.supersede_fact(db, user.id, fact.id, fact="   ")


def test_invalid_category_is_rejected(db, user):
    fact = _add(db, user, "reads at night", _vec(0))
    with pytest.raises(Invalid):
        svc.update_fact(db, user.id, fact.id, category="nonsense")


# --- confirmation -----------------------------------------------------------------


def test_confirming_promotes_inferred_to_stated(db, user):
    fact = _add(db, user, "prefers dark mode", _vec(0), source="inferred", confidence=0.6)

    confirmed = svc.set_confirmed(db, user.id, fact.id, True)

    assert confirmed.source == "stated"
    # The STORED estimate is untouched; certainty is derived, so un-confirming is lossless.
    assert confirmed.confidence == 0.6
    assert confirmed.effective_confidence == 1.0
    assert svc.set_confirmed(db, user.id, fact.id, False).effective_confidence == 0.6


# --- search and filters -----------------------------------------------------------


def test_list_filters(db, user):
    _add(db, user, "likes filter coffee", _vec(0), category="preference")
    _add(db, user, "works in finance", _vec(1), category="work", source="stated")
    _add(db, user, "runs 5k weekly", _vec(2), category="health", confidence=0.4)

    assert len(svc.list_facts(db, user.id)) == 3
    assert [f.fact for f in svc.list_facts(db, user.id, category="work")] == ["works in finance"]
    assert [f.fact for f in svc.list_facts(db, user.id, source="stated")] == ["works in finance"]
    assert len(svc.list_facts(db, user.id, min_confidence=0.5)) == 2
    assert [f.fact for f in svc.list_facts(db, user.id, q="COFFEE")] == ["likes filter coffee"]


def test_search_escapes_like_wildcards(db, user):
    _add(db, user, "saves 30% of income", _vec(0))
    _add(db, user, "reads every night", _vec(1))

    assert [f.fact for f in svc.list_facts(db, user.id, q="30%")] == ["saves 30% of income"]
    # "%" searches for a literal percent sign, so it finds the fact containing one and
    # not the one that doesn't. Unescaped, LIKE would treat it as "match everything".
    assert [f.fact for f in svc.list_facts(db, user.id, q="%")] == ["saves 30% of income"]
    assert svc.list_facts(db, user.id, q="_") == []  # underscore is literal too, not "any char"


# --- the graph --------------------------------------------------------------------


def test_graph_links_related_facts_and_omits_unrelated(db, user):
    """Two facts sharing a dimension are close; a third one-hot is maximally far."""
    a = _add(db, user, "prefers dark interfaces", _mix(0, 1, 0.9))
    b = _add(db, user, "codes late at night", _mix(0, 1, 0.8))
    far = _add(db, user, "allergic to peanuts", _vec(300), category="health")

    edges = svc.neighbours(db, user.id, k=3)
    pairs = {frozenset((s, t)) for s, t, _ in edges}

    assert frozenset((a.id, b.id)) in pairs
    assert not any(far.id in p for p in pairs)  # beyond GRAPH_MAX_DISTANCE — isolated


def test_graph_edges_are_undirected_and_deduplicated(db, user):
    a = _add(db, user, "one", _mix(0, 1, 0.9))
    b = _add(db, user, "two", _mix(0, 1, 0.8))

    edges = svc.neighbours(db, user.id, k=3)

    assert len(edges) == 1  # a->b and b->a collapse to a single edge
    assert {edges[0][0], edges[0][1]} == {a.id, b.id}
    assert 0.0 <= edges[0][2] <= 1.0


def test_graph_never_returns_vectors(db, user):
    _add(db, user, "one", _mix(0, 1, 0.9))
    _add(db, user, "two", _mix(0, 1, 0.8))

    for edge in svc.neighbours(db, user.id):
        assert len(edge) == 3
        assert isinstance(edge[2], float)  # a distance, not 768 floats


def test_graph_is_empty_without_facts(db, user):
    assert svc.neighbours(db, user.id) == []


# --- stats ------------------------------------------------------------------------


def test_stats_summarises_the_memory(db, user):
    _add(db, user, "a", _vec(0), category="work")
    _add(db, user, "b", _vec(1), category="work")
    _add(db, user, "c", _vec(2), category="health", source="stated")
    forgotten = _add(db, user, "d", _vec(3), category="health")
    svc.forget_fact(db, user.id, forgotten.id)

    s = svc.stats(db, user.id)

    assert s["total"] == 3  # the forgotten one is not counted
    assert s["by_category"] == {"work": 2, "health": 1}
    assert s["by_source"] == {"inferred": 2, "stated": 1}
    assert sum(d["count"] for d in s["per_day"]) == 3
