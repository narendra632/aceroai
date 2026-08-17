"""The memory API — the first HTTP surface `profile_facts` has ever had.

Covers what the Knowledge page depends on: listing and filtering, the graph shape,
provenance resolution, correction-by-supersession, confirmation, and reversible forgetting.
"""

import uuid

from app.config import settings
from app.db.models import ChatSession, Message, ProfileFact
from app.services import memory as svc


def _onehot(i: int, val: float = 1.0) -> list[float]:
    v = [0.0] * settings.embed_dim
    v[i] = val
    return v


def _mix(i: int, j: int, w: float = 0.9) -> list[float]:
    v = [0.0] * settings.embed_dim
    v[i] = 1.0
    v[j] = w
    return v


def _fact(db, user, text, vec, **kw):
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


# --- reading ----------------------------------------------------------------------


def test_facts_require_auth(client):
    assert client.get("/api/memory/facts").status_code == 401
    assert client.get("/api/memory/graph").status_code == 401
    assert client.get("/api/memory/stats").status_code == 401


def test_list_and_filter_facts(auth_client, db, user):
    _fact(db, user, "likes filter coffee", _onehot(0))
    _fact(db, user, "works in finance", _onehot(1), category="work", source="stated")

    all_facts = auth_client.get("/api/memory/facts").json()
    assert {f["fact"] for f in all_facts} == {"likes filter coffee", "works in finance"}

    only_work = auth_client.get("/api/memory/facts", params={"category": "work"}).json()
    assert [f["fact"] for f in only_work] == ["works in finance"]

    searched = auth_client.get("/api/memory/facts", params={"q": "coffee"}).json()
    assert [f["fact"] for f in searched] == ["likes filter coffee"]


def test_list_excludes_superseded_unless_asked(auth_client, db, user):
    old = _fact(db, user, "lives in Pune", _onehot(0))
    auth_client.patch(f"/api/memory/facts/{old.id}", json={"fact": "lives in Bengaluru"})

    current = auth_client.get("/api/memory/facts").json()
    assert [f["fact"] for f in current] == ["lives in Bengaluru"]

    history = auth_client.get("/api/memory/facts", params={"status": "all"}).json()
    assert {f["fact"] for f in history} == {"lives in Pune", "lives in Bengaluru"}


def test_stats_summarise_the_memory(auth_client, db, user):
    _fact(db, user, "a", _onehot(0), category="work")
    _fact(db, user, "b", _onehot(1), category="health", source="stated")

    body = auth_client.get("/api/memory/stats").json()

    assert body["total"] == 2
    assert body["by_category"] == {"work": 1, "health": 1}
    assert body["by_source"] == {"inferred": 1, "stated": 1}
    assert sum(d["count"] for d in body["per_day"]) == 2


# --- the graph --------------------------------------------------------------------


def test_graph_returns_nodes_and_edges_without_vectors(auth_client, db, user):
    a = _fact(db, user, "prefers dark interfaces", _mix(0, 1, 0.9))
    b = _fact(db, user, "codes late at night", _mix(0, 1, 0.8))

    body = auth_client.get("/api/memory/graph").json()

    assert {n["id"] for n in body["nodes"]} == {str(a.id), str(b.id)}
    assert len(body["edges"]) == 1
    assert {body["edges"][0]["source"], body["edges"][0]["target"]} == {str(a.id), str(b.id)}

    # The whole point of computing this server-side: no 768-dimensional payload.
    assert "embedding" not in body["nodes"][0]
    assert set(body["nodes"][0]) == {
        "id",
        "fact",
        "category",
        "confidence",
        "source",
        "valid_from",
    }


def test_graph_distance_cutoff_is_adjustable(auth_client, db, user):
    _fact(db, user, "one", _onehot(0))
    _fact(db, user, "two", _onehot(1))  # orthogonal — distance 1.0

    assert auth_client.get("/api/memory/graph").json()["edges"] == []
    loose = auth_client.get("/api/memory/graph", params={"max_distance": 1.5}).json()
    assert len(loose["edges"]) == 1


def test_graph_is_empty_for_a_new_user(auth_client):
    body = auth_client.get("/api/memory/graph").json()
    assert body == {
        "nodes": [],
        "edges": [],
        "truncated": False,
        "total": 0,
        "render_limit": svc.GRAPH_LIMIT,
        "needs_faster_layout": False,
    }


def test_graph_reports_truncation_rather_than_hiding_it(auth_client, db, user, monkeypatch):
    """Showing a subset of someone's memory as if it were all of it is a quiet lie."""
    monkeypatch.setattr("app.services.memory.GRAPH_LIMIT", 2)
    for i in range(4):
        _fact(db, user, f"fact {i}", _onehot(i))

    body = auth_client.get("/api/memory/graph").json()

    assert len(body["nodes"]) == 2
    assert body["truncated"] is True
    assert body["total"] == 4


# --- provenance -------------------------------------------------------------------


def test_detail_resolves_the_conversation_a_fact_came_from(auth_client, db, user):
    session = ChatSession(user_id=user.id, channel="web", title="chat")
    db.add(session)
    db.flush()
    message = Message(session_id=session.id, role="user", content="I collect vinyl")
    db.add(message)
    db.commit()

    fact = _fact(db, user, "collects vinyl", _onehot(0), source_ref=message.id)

    body = auth_client.get(f"/api/memory/facts/{fact.id}").json()
    assert body["source_session_id"] == str(session.id)


def test_detail_without_provenance_says_so(auth_client, db, user):
    fact = _fact(db, user, "seeded fact", _onehot(0))
    body = auth_client.get(f"/api/memory/facts/{fact.id}").json()
    assert body["source_session_id"] is None
    assert body["previous"] is None


def test_detail_exposes_the_replaced_version(auth_client, db, user):
    old = _fact(db, user, "works at Company A", _onehot(0), category="work")
    new_id = auth_client.patch(
        f"/api/memory/facts/{old.id}", json={"fact": "works at Company B"}
    ).json()["id"]

    body = auth_client.get(f"/api/memory/facts/{new_id}").json()
    assert body["previous"]["fact"] == "works at Company A"
    assert body["previous"]["status"] == "superseded"


# --- correcting -------------------------------------------------------------------


def test_editing_text_supersedes_and_re_embeds(auth_client, db, user):
    old = _fact(db, user, "drives a hatchback", _onehot(0))

    body = auth_client.patch(
        f"/api/memory/facts/{old.id}", json={"fact": "drives an electric car"}
    ).json()

    assert body["id"] != str(old.id)
    assert body["fact"] == "drives an electric car"

    replacement = db.get(ProfileFact, uuid.UUID(body["id"]))
    assert replacement.embedding is not None, "a replacement without an embedding is unrecallable"

    db.refresh(old)
    assert old.status == "superseded"
    assert old.superseded_by == replacement.id


def test_metadata_only_edit_keeps_the_same_fact(auth_client, db, user):
    fact = _fact(db, user, "saves aggressively", _onehot(0), category="other")

    body = auth_client.patch(f"/api/memory/facts/{fact.id}", json={"category": "finance"}).json()

    assert body["id"] == str(fact.id)
    assert body["category"] == "finance"
    assert body["superseded_by"] is None


def test_invalid_category_is_rejected(auth_client, db, user):
    fact = _fact(db, user, "x", _onehot(0))
    r = auth_client.patch(f"/api/memory/facts/{fact.id}", json={"category": "nope"})
    assert r.status_code == 400


def test_confirm_promotes_to_stated(auth_client, db, user):
    fact = _fact(db, user, "prefers dark mode", _onehot(0), source="inferred", confidence=0.5)

    body = auth_client.post(f"/api/memory/facts/{fact.id}/confirm").json()

    assert body["source"] == "stated"
    assert body["confidence"] == 1.0


def test_confirm_is_reversible_without_losing_the_original_confidence(auth_client, db, user):
    """A misclick on Confirm must be undoable, and un-confirming must not invent a
    confidence — the model's own estimate is preserved rather than overwritten."""
    fact = _fact(db, user, "prefers dark mode", _onehot(0), source="inferred", confidence=0.55)

    auth_client.post(f"/api/memory/facts/{fact.id}/confirm")
    body = auth_client.post(f"/api/memory/facts/{fact.id}/unconfirm").json()

    assert body["source"] == "inferred"
    assert body["confidence"] == 0.55  # not 1.0, and not some invented default


def test_editing_the_text_confirms_it(auth_client, db, user):
    """Rewriting a belief in your own words IS confirming it — being asked to then press
    Confirm on text you just typed would be asking you to vouch for yourself."""
    old = _fact(db, user, "works at Company A", _onehot(0), source="inferred", confidence=0.6)

    body = auth_client.patch(
        f"/api/memory/facts/{old.id}", json={"fact": "works at Company B"}
    ).json()

    assert body["source"] == "stated"
    assert body["confidence"] == 1.0


def test_model_supersession_stays_inferred(auth_client, db, user):
    """The opposite case: when the MODEL replaces a fact the user had confirmed, the
    replacement must NOT inherit 'stated' — that would launder a guess into something the
    user appears to have said."""
    from app.services import memory as svc

    old = _fact(db, user, "works at Company A", _onehot(0), source="stated")
    new = svc.supersede_fact(
        db, user.id, old.id, fact="works at Company B", embedding=_onehot(1), source="inferred"
    )

    assert new.source == "inferred"


# --- forgetting -------------------------------------------------------------------


def test_forget_then_restore(auth_client, db, user):
    fact = _fact(db, user, "temporary belief", _onehot(0))

    assert auth_client.delete(f"/api/memory/facts/{fact.id}").status_code == 204
    assert auth_client.get("/api/memory/facts").json() == []
    assert auth_client.get(f"/api/memory/facts/{fact.id}").status_code == 404

    restored = auth_client.post(f"/api/memory/facts/{fact.id}/restore").json()
    assert restored["fact"] == "temporary belief"
    assert len(auth_client.get("/api/memory/facts").json()) == 1


def test_forgotten_fact_is_gone_from_the_graph(auth_client, db, user):
    a = _fact(db, user, "one", _mix(0, 1, 0.9))
    _fact(db, user, "two", _mix(0, 1, 0.8))

    auth_client.delete(f"/api/memory/facts/{a.id}")

    body = auth_client.get("/api/memory/graph").json()
    assert [n["fact"] for n in body["nodes"]] == ["two"]
    assert body["edges"] == []


def test_another_users_fact_is_untouchable(auth_client, db, other_user):
    theirs = _fact(db, other_user, "their belief", _onehot(0))

    assert auth_client.get(f"/api/memory/facts/{theirs.id}").status_code == 404
    assert auth_client.delete(f"/api/memory/facts/{theirs.id}").status_code == 404
    assert auth_client.post(f"/api/memory/facts/{theirs.id}/confirm").status_code == 404
    assert (
        auth_client.patch(f"/api/memory/facts/{theirs.id}", json={"category": "work"}).status_code
        == 404
    )

    db.refresh(theirs)
    assert theirs.fact == "their belief"
    assert theirs.status == "active"


def test_graph_edges_never_reference_a_fact_that_is_not_drawn(auth_client, db, user, monkeypatch):
    """When the node list is capped, the edge list must be capped to the SAME set.

    Otherwise the server hands back edges pointing at facts the client was never given —
    silently dropped on the client, so the picture looks fine while the payload carries
    junk and the "showing N of M" count quietly stops matching the drawing.
    """
    monkeypatch.setattr("app.services.memory.GRAPH_LIMIT", 3)
    for i in range(8):
        _fact(db, user, f"fact number {i}", _mix(0, i + 1, 0.9))

    body = auth_client.get("/api/memory/graph", params={"max_distance": 2.0}).json()
    drawn = {n["id"] for n in body["nodes"]}

    assert len(drawn) == 3
    assert body["truncated"] is True
    for e in body["edges"]:
        assert e["source"] in drawn, "edge points at a fact that was never sent"
        assert e["target"] in drawn, "edge points at a fact that was never sent"


# --- pagination and the graph ceiling ----------------------------------------------


def test_list_paginates_and_respects_the_active_filter(auth_client, db, user, monkeypatch):
    """Load-more must continue WITHIN the current filter. Paging through everything and
    filtering the leftovers would show a partial category and call it complete."""
    monkeypatch.setattr("app.services.memory.PAGE_SIZE", 2)
    for i in range(5):
        _fact(db, user, f"work fact {i}", _onehot(i), category="work")
    for i in range(3):
        _fact(db, user, f"health fact {i}", _onehot(50 + i), category="health")

    page1 = auth_client.get("/api/memory/facts", params={"category": "work", "limit": 2}).json()
    page2 = auth_client.get(
        "/api/memory/facts", params={"category": "work", "limit": 2, "offset": 2}
    ).json()
    page3 = auth_client.get(
        "/api/memory/facts", params={"category": "work", "limit": 2, "offset": 4}
    ).json()

    assert len(page1) == 2 and len(page2) == 2 and len(page3) == 1  # 5 work facts, not 8
    seen = [f["fact"] for f in page1 + page2 + page3]
    assert len(set(seen)) == 5, "pages overlapped or skipped"
    assert all(f.startswith("work") for f in seen), "a health fact leaked into a work page"


def test_search_paginates_too(auth_client, db, user, monkeypatch):
    monkeypatch.setattr("app.services.memory.PAGE_SIZE", 2)
    for i in range(4):
        _fact(db, user, f"about cricket {i}", _onehot(i))
    _fact(db, user, "about football", _onehot(90))

    page1 = auth_client.get("/api/memory/facts", params={"q": "cricket", "limit": 2}).json()
    page2 = auth_client.get(
        "/api/memory/facts", params={"q": "cricket", "limit": 2, "offset": 2}
    ).json()

    assert len(page1) == 2 and len(page2) == 2
    assert all("cricket" in f["fact"] for f in page1 + page2)


def test_graph_announces_when_it_needs_a_faster_layout(auth_client, db, user, monkeypatch):
    """The moment to switch to Barnes-Hut should announce itself in the interface, not sit
    in a document nobody re-reads."""
    monkeypatch.setattr("app.services.memory.GRAPH_LIMIT", 10)

    for i in range(7):
        _fact(db, user, f"fact {i}", _onehot(i))
    assert auth_client.get("/api/memory/graph").json()["needs_faster_layout"] is False

    _fact(db, user, "fact 8", _onehot(70))
    body = auth_client.get("/api/memory/graph").json()
    assert body["needs_faster_layout"] is True  # warned BEFORE anything is hidden
    assert body["truncated"] is False
    assert body["render_limit"] == 10


def test_graph_draws_up_to_the_ceiling_then_reports_the_rest(auth_client, db, user, monkeypatch):
    monkeypatch.setattr("app.services.memory.GRAPH_LIMIT", 4)
    for i in range(9):
        _fact(db, user, f"fact {i}", _onehot(i))

    body = auth_client.get("/api/memory/graph").json()

    assert len(body["nodes"]) == 4
    assert body["total"] == 9
    assert body["truncated"] is True
    assert body["needs_faster_layout"] is True
