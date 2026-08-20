"""Memory service: read, correct, confirm and forget the facts the assistant has learned.

The split with `core/memory.py` is deliberate and mirrors the rest of the codebase:

- **`core/memory.py`** owns the *behaviour* — extracting facts from a turn, embedding them,
  recalling them into context.
- **`services/memory.py`** (this module) owns the *rules* — what counts as a visible fact,
  and every mutation a user can make to one.

`live()` below is the **single home** for the visibility filter. The REST API, the graph
endpoint and `core.memory`'s recall all route through it, so no caller can forget it and a
forgotten fact cannot leak back into the model's context.

Embeddings are never computed here. Producing one is an async network call and this layer is
sync, so callers pass a precomputed vector — exactly the convention `core.memory.recall_facts`
already uses.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, case, func, select, true
from sqlalchemy.orm import Session, aliased

from app.config import settings
from app.db.models import ChatSession, Message, ProfileFact
from app.services.errors import Invalid, NotFound

# One constant used to do three unrelated jobs. Splitting them, because they are governed
# by completely different things: a page size is a scrolling decision, a render ceiling is
# a frame-budget measurement, and a request ceiling is abuse protection.

# How many facts one page of the list returns. Beyond this the client asks for more.
PAGE_SIZE = 100
# The most any single list request may ask for.
LIST_MAX = 500
# How many facts the graph will draw. MEASURED: the force simulation costs ~3.5 ms per
# frame at 800 nodes (~21% of a 16.7 ms frame budget on a desktop), which is the last
# comfortable size before the O(n²) repulsion pass starts eating whole frames. Past this
# the fix is a Barnes-Hut quadtree — the UI says so when the ceiling is reached, so the
# trigger is visible where it will actually be noticed rather than buried in a document.
GRAPH_LIMIT = 800
# Warn at 80% of the ceiling, so it is announced BEFORE it starts hiding facts. Kept as a
# ratio rather than a precomputed threshold: a derived constant evaluated once at import
# silently goes stale the moment GRAPH_LIMIT changes.
GRAPH_WARN_RATIO = 0.8


def graph_warn_at() -> int:
    return int(GRAPH_LIMIT * GRAPH_WARN_RATIO)


CATEGORIES = ("preference", "health", "work", "finance", "relationship", "other")
SOURCES = ("stated", "inferred")
STATUSES = ("active", "superseded", "rejected")

# How many nearest neighbours each fact links to in the graph.
GRAPH_NEIGHBOURS = 3
# Cosine distance beyond which two facts are not considered related. Without a cutoff a
# kNN graph always draws k edges per node, so unrelated facts get joined and the picture
# implies a structure that isn't there. An isolated node is honest information.
#
# MEASURED, not guessed. Against 11 real facts embedded by gemini-embedding-001, every
# pair falls between 0.13 and 0.48 — real embeddings of one person's facts cluster far
# more tightly than the 0..1 range suggests. A 0.55 cutoff therefore excluded nothing
# (31 of a possible 55 edges: a hairball). At k=3 / 0.32 the same data yields ~18 edges,
# where the clusters are actually legible.
#
# For calibration, the closest real pairs were "uses VS Code" <-> "uses the Claude Code
# extension" (0.130) and "has sisters" <-> "celebrates Rakshabandhan" (0.189) — the
# second sharing no words at all, which is the whole point of embedding rather than
# matching text.
GRAPH_MAX_DISTANCE = 0.32


def live(stmt: Select) -> Select:
    """Restrict a `ProfileFact` query to rows the user has not forgotten.

    The one place this filter exists. `core.memory` imports it rather than repeating the
    predicate, so recall and the API can never disagree about what is visible.
    """
    return stmt.where(ProfileFact.deleted_at.is_(None))


# --- the one writer ---------------------------------------------------------------
#
# Every path that creates a fact goes through `remember`: the assistant's tools, the
# background extractor, and anything added later. Memory is the one subsystem in this
# project that never got a front door, and that is exactly why it grew a write path with
# a dedup rule nobody could point at — a rule that silently deleted a fact the user had
# asked for by name.

#: What `remember` did. Returned instead of a bare bool because the outcomes are genuinely
#: different events and the caller (and the model) must be able to tell them apart —
#: "stored" and "flagged" both mean the fact exists, "superseded" means an older belief was
#: retired, "unchanged" means nothing was written, and none may be reported as any other.
STORED = "stored"
SUPERSEDED = "superseded"
FLAGGED = "flagged"
UNCHANGED = "unchanged"


@dataclass(frozen=True)
class WriteResult:
    action: str
    fact: ProfileFact
    #: The fact this one superseded or is suspected of duplicating, when there is one.
    related: ProfileFact | None = None


def _same_text_active(db: Session, user_id: uuid.UUID, text: str) -> ProfileFact | None:
    """An active fact whose text is the same sentence, ignoring case and spacing.

    Compared in the database rather than in Python so it costs one indexed-ish lookup
    instead of loading every fact, and so the comparison is the same for every caller.
    """
    normalised = " ".join(text.split())
    return db.execute(
        live(select(ProfileFact))
        .where(
            ProfileFact.user_id == user_id,
            ProfileFact.status == "active",
            func.lower(func.regexp_replace(ProfileFact.fact, r"\s+", " ", "g"))
            == normalised.lower(),
        )
        .limit(1)
    ).scalar_one_or_none()


def nearest_active(
    db: Session, user_id: uuid.UUID, vec: Sequence[float]
) -> tuple[ProfileFact, float] | None:
    """The closest active fact to `vec`, with its cosine distance. None if there are none."""
    row = db.execute(
        live(select(ProfileFact, ProfileFact.embedding.cosine_distance(list(vec)).label("d")))
        .where(
            ProfileFact.user_id == user_id,
            ProfileFact.status == "active",
            ProfileFact.embedding.isnot(None),
        )
        .order_by(ProfileFact.embedding.cosine_distance(list(vec)))
        .limit(1)
    ).first()
    return (row[0], float(row[1])) if row is not None else None


def remember(
    db: Session,
    user_id: uuid.UUID,
    fact: str,
    *,
    category: str = "other",
    embedding: Sequence[float] | None = None,
    source: str = "inferred",
    source_ref: uuid.UUID | None = None,
    replaces: uuid.UUID | None = None,
    confidence: float = 0.8,
) -> WriteResult:
    """Store a fact, or supersede one it replaces. **Never discards.**

    Three outcomes:

    - `replaces` names a fact  ->  **SUPERSEDED**. The old belief is retired and linked to
      the new one, so a change survives as history rather than as an overwrite.
    - no hint, and nothing similar  ->  **STORED**.
    - no hint, but an existing active fact sits within `memory_dedup_distance`  ->
      **FLAGGED**: stored anyway, with `possible_duplicate_of` pointing at its suspected
      twin.

    That last branch is the whole reason this function exists. It used to be a delete.
    Cosine distance measures subject matter, not identity, and the measurement is not
    close: `"Narendra has completed the AI-901 certification"` and the same sentence with
    `AI-103` are **0.098** apart — inside the 0.12 threshold — while two phrasings of the
    same family fact are 0.216 apart, outside it. The threshold is wrong in both
    directions at once, so it cannot be repaired by moving it.

    Dropping is the destructive move, so dropping is the one that needs evidence. A stored
    near-duplicate is visible on the Knowledge page and mergeable in one click; a deleted
    fact leaves nothing to notice.
    """
    text = (fact or "").strip()
    if not text:
        raise Invalid("a fact needs text")
    _validate(category, confidence)

    if replaces is not None:
        target = get_fact(db, user_id, replaces)
        replacement = supersede_fact(
            db,
            user_id,
            target.id,
            fact=text,
            embedding=embedding,
            category=category,
            confidence=confidence,
            source=source,
        )
        return WriteResult(SUPERSEDED, replacement, target)

    # The one case where "this is a repeat" is a FACT rather than a judgement.
    #
    # The whole argument for storing near-duplicates is that cosine distance cannot tell a
    # restatement from a change: AI-901 and AI-103 measure 0.098 apart and are different
    # facts. Identical text carries no such ambiguity — there is nothing to lose by not
    # writing it, because every character of it is already stored.
    #
    # This is not theoretical. MEASURED live: asking the assistant to remember something
    # makes it call `remember_fact`, and then the background extractor reads the same turn,
    # proposes the same sentence, and stores it again — so every explicit "remember X"
    # produced two identical rows and recall returned both. The store-don't-drop rule was
    # right and this is its one principled exception.
    existing = _same_text_active(db, user_id, text)
    if existing is not None:
        return WriteResult(UNCHANGED, existing)

    twin: ProfileFact | None = None
    if embedding is not None:
        near = nearest_active(db, user_id, embedding)
        if near is not None and near[1] < settings.memory_dedup_distance:
            twin = near[0]

    row = ProfileFact(
        user_id=user_id,
        fact=text,
        category=category,
        confidence=confidence,
        source=source,
        source_ref=source_ref,
        status="active",
        embedding=list(embedding) if embedding is not None else None,
        possible_duplicate_of=twin.id if twin is not None else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return WriteResult(FLAGGED if twin is not None else STORED, row, twin)


def correct(
    db: Session,
    db_user_id: uuid.UUID,
    fact_id: uuid.UUID,
    new_text: str,
    *,
    embedding: Sequence[float] | None = None,
    category: str | None = None,
    confidence: float | None = None,
) -> WriteResult:
    """Replace a fact with a corrected version the user has just told us in their own
    words. Recorded as `stated`, because saying it *is* confirming it."""
    replacement = supersede_fact(
        db,
        db_user_id,
        fact_id,
        fact=new_text,
        embedding=embedding,
        category=category,
        confidence=confidence,
        source="stated",
    )
    previous = db.execute(
        select(ProfileFact).where(ProfileFact.superseded_by == replacement.id)
    ).scalar_one_or_none()
    return WriteResult(SUPERSEDED, replacement, previous)


def clear_duplicate_flag(db: Session, user_id: uuid.UUID, fact_id: uuid.UUID) -> ProfileFact:
    """Dismiss a suspected duplicate: these two facts are genuinely different.

    The flag is a question, not a verdict, so it needs an answer that is not "delete one of
    them". Answering it here is what keeps the Knowledge page from accumulating a permanent
    list of warnings nobody can clear.
    """
    row = get_fact(db, user_id, fact_id)
    row.possible_duplicate_of = None
    db.commit()
    db.refresh(row)
    return row


def _validate(category: str | None, confidence: float | None) -> None:
    if category is not None and category not in CATEGORIES:
        raise Invalid(f"category must be one of: {', '.join(CATEGORIES)}")
    if confidence is not None and not (0.0 <= confidence <= 1.0):
        raise Invalid("confidence must be between 0 and 1")


def get_fact(
    db: Session, user_id: uuid.UUID, fact_id: uuid.UUID, *, include_deleted: bool = False
) -> ProfileFact:
    """Fetch one owned fact. `include_deleted` is only for restore — to every other caller
    a forgotten fact must look exactly like one that never existed."""
    fact = db.get(ProfileFact, fact_id)
    if fact is None or fact.user_id != user_id:
        raise NotFound("fact not found")
    if fact.deleted_at is not None and not include_deleted:
        raise NotFound("fact not found")
    return fact


def list_facts(
    db: Session,
    user_id: uuid.UUID,
    *,
    category: str | None = None,
    status: str | None = "active",
    source: str | None = None,
    min_confidence: float | None = None,
    q: str | None = None,
    limit: int = PAGE_SIZE,
    offset: int = 0,
) -> list[ProfileFact]:
    """The user's facts, newest first.

    `status` defaults to `"active"` — the memory as it currently stands. Pass `None` to
    include superseded and rejected facts, which is what the history view wants.

    `q` is a case-insensitive substring match, consistent with journal search. The same
    caveat applies: it matches characters, not meaning. Semantic search over these very
    embeddings is the better end state and is on the roadmap.
    """
    stmt = live(select(ProfileFact).where(ProfileFact.user_id == user_id))
    if category is not None:
        stmt = stmt.where(ProfileFact.category == category)
    if status is not None:
        stmt = stmt.where(ProfileFact.status == status)
    if source is not None:
        stmt = stmt.where(ProfileFact.source == source)
    if min_confidence is not None:
        # Filter on the *effective* confidence, or a confirmed fact whose stored estimate
        # was low would be filtered out of a view that should always include it.
        stmt = stmt.where(
            case((ProfileFact.source == "stated", 1.0), else_=ProfileFact.confidence)
            >= min_confidence
        )
    if q and q.strip():
        # escape LIKE wildcards so a literal % or _ searches for itself
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(ProfileFact.fact.ilike(f"%{escaped}%", escape="\\"))
    stmt = stmt.order_by(ProfileFact.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def update_fact(
    db: Session,
    user_id: uuid.UUID,
    fact_id: uuid.UUID,
    *,
    fact: str | None = None,
    embedding: Sequence[float] | None = None,
    category: str | None = None,
    confidence: float | None = None,
) -> ProfileFact:
    """Correct a fact.

    Two different operations hide behind "edit", and conflating them would be wrong:

    - **The text changes** → the old belief is *superseded*, not overwritten. A new row
      becomes active and the old one records that it was replaced. See `supersede_fact`.
    - **Only metadata changes** (category, confidence) → the same belief, re-labelled.
      Updated in place; superseding here would litter the history with non-events.
    """
    _validate(category, confidence)
    if fact is not None and fact.strip() and fact.strip() != get_fact(db, user_id, fact_id).fact:
        return supersede_fact(
            db,
            user_id,
            fact_id,
            fact=fact,
            embedding=embedding,
            category=category,
            confidence=confidence,
            # Rewriting a belief in your own words IS confirming it — you authored this
            # sentence deliberately. Making the user then press Confirm on text they just
            # typed would be asking them to vouch for themselves.
            source="stated",
        )

    row = get_fact(db, user_id, fact_id)
    if category is not None:
        row.category = category
    if confidence is not None:
        row.confidence = confidence
    db.commit()
    db.refresh(row)
    return row


def supersede_fact(
    db: Session,
    user_id: uuid.UUID,
    fact_id: uuid.UUID,
    *,
    fact: str,
    embedding: Sequence[float] | None = None,
    category: str | None = None,
    confidence: float | None = None,
    source: str | None = None,
) -> ProfileFact:
    """Replace a fact with a corrected version, keeping the original as history.

    The old row becomes `status='superseded'` and points at its replacement through
    `superseded_by`. Recall filters `status='active'`, so the old belief stops reaching the
    model the moment this commits — no change to the recall query is needed.

    ⚠ `embedding` should be the vector for the **new** text. A replacement stored without
    one is invisible to semantic recall: it would show in the UI while never informing a
    conversation again, which is a worse failure than refusing the edit. Callers that can
    embed must do so; the API does.
    """
    text = (fact or "").strip()
    if not text:
        raise Invalid("a fact needs text")
    _validate(category, confidence)

    old = get_fact(db, user_id, fact_id)
    replacement = ProfileFact(
        user_id=user_id,
        fact=text,
        category=category or old.category,
        confidence=confidence if confidence is not None else old.confidence,
        source=source or old.source,
        source_ref=old.source_ref,
        status="active",
        embedding=list(embedding) if embedding is not None else None,
    )
    db.add(replacement)
    db.flush()  # need the replacement's id before the old row can point at it

    old.status = "superseded"
    old.superseded_by = replacement.id
    db.commit()
    db.refresh(replacement)
    return replacement


def set_confirmed(
    db: Session, user_id: uuid.UUID, fact_id: uuid.UUID, confirmed: bool
) -> ProfileFact:
    """Confirm or un-confirm a fact — a toggle, because confirming by mistake must be
    undoable without hunting for a different control.

    Every fact arrives as an LLM's *inference*, which can be wrong. Confirming is how a
    guess becomes authoritative, and it is the first place `source='stated'` is ever
    written despite the column existing since migration 001.

    `confidence` is deliberately **not** touched. It holds the model's own estimate; the
    certainty that confirmation implies is derived at read time by
    `ProfileFact.effective_confidence`. Overwriting it would make un-confirming lossy —
    there would be no original number to go back to.
    """
    row = get_fact(db, user_id, fact_id)
    row.source = "stated" if confirmed else "inferred"
    db.commit()
    db.refresh(row)
    return row


def forget_fact(db: Session, user_id: uuid.UUID, fact_id: uuid.UUID) -> None:
    """Soft delete, so forgetting can be undone. The row stays; `live()` hides it from
    every reader, including recall."""
    row = get_fact(db, user_id, fact_id)
    row.deleted_at = dt.datetime.now(dt.UTC)
    db.commit()


def restore_fact(db: Session, user_id: uuid.UUID, fact_id: uuid.UUID) -> ProfileFact:
    """Undo a forget. Restoring a fact that is already live is a no-op rather than an
    error, so a double-tap on Undo cannot fail."""
    row = get_fact(db, user_id, fact_id, include_deleted=True)
    row.deleted_at = None
    db.commit()
    db.refresh(row)
    return row


def provenance(db: Session, user_id: uuid.UUID, fact: ProfileFact) -> uuid.UUID | None:
    """The chat session a fact was learned from, or None if it has no conversational origin.

    `source_ref` points at a *message*; what the user wants to open is the *conversation*.
    Resolved on demand rather than joined into every list, because only the detail panel
    shows it.
    """
    if fact.source_ref is None:
        return None
    row = db.execute(
        select(ChatSession.id)
        .join(Message, Message.session_id == ChatSession.id)
        .where(Message.id == fact.source_ref, ChatSession.user_id == user_id)
    ).scalar_one_or_none()
    return row


def previous_version(db: Session, user_id: uuid.UUID, fact: ProfileFact) -> ProfileFact | None:
    """The fact this one replaced, if any — what makes `supersede_fact`'s preserved history
    actually reachable rather than merely stored."""
    return db.execute(
        select(ProfileFact).where(
            ProfileFact.user_id == user_id,
            ProfileFact.superseded_by == fact.id,
        )
    ).scalar_one_or_none()


def neighbours(
    db: Session,
    user_id: uuid.UUID,
    *,
    k: int = GRAPH_NEIGHBOURS,
    max_distance: float = GRAPH_MAX_DISTANCE,
    among: Sequence[uuid.UUID] | None = None,
) -> list[tuple[uuid.UUID, uuid.UUID, float]]:
    """The graph's edges: each fact linked to its `k` nearest neighbours by meaning.

    Returns `(source_id, target_id, distance)` with each undirected pair appearing **once**,
    and **never returns the embedding vectors themselves** — the whole point of computing
    this server-side is that 768-dimensional vectors never cross the wire.

    One query, via a lateral join: for every fact, the inner select is re-run against that
    fact's own vector. The alternative is N round-trips.

    `among` restricts BOTH ends of every edge to a given set of facts. The caller draws a
    bounded number of nodes, so the edges must be bounded to the same set — otherwise the
    response carries edges pointing at facts the client was never sent. They would be
    silently dropped client-side, which looks fine and is not: the payload grows with the
    whole memory while the picture shows a slice of it.
    """
    if k <= 0:
        return []
    if among is not None and len(among) < 2:
        return []

    f = aliased(ProfileFact, name="f")
    o = aliased(ProfileFact, name="o")
    dist = f.embedding.cosine_distance(o.embedding).label("dist")

    inner_where = [
        o.user_id == user_id,
        o.id != f.id,
        o.status == "active",
        o.deleted_at.is_(None),
        o.embedding.isnot(None),
    ]
    outer_where = [
        f.user_id == user_id,
        f.status == "active",
        f.deleted_at.is_(None),
        f.embedding.isnot(None),
    ]
    if among is not None:
        ids = list(among)
        inner_where.append(o.id.in_(ids))
        outer_where.append(f.id.in_(ids))

    nearest = (
        select(o.id.label("target"), dist).where(*inner_where).order_by(dist).limit(k).lateral("n")
    )
    stmt = (
        select(f.id.label("source"), nearest.c.target, nearest.c.dist)
        .select_from(f)
        .join(nearest, true())
        .where(*outer_where, nearest.c.dist <= max_distance)
    )

    # A→B and B→A are the same edge. Keep the first seen, keyed on the unordered pair.
    seen: dict[frozenset[uuid.UUID], tuple[uuid.UUID, uuid.UUID, float]] = {}
    for source, target, distance in db.execute(stmt):
        key = frozenset((source, target))
        if key not in seen:
            seen[key] = (source, target, float(distance))
    return list(seen.values())


def stats(db: Session, user_id: uuid.UUID) -> dict:
    """Shape of the memory: counts by attribute, and growth over time for the scrubber."""
    base = live(select(ProfileFact).where(ProfileFact.user_id == user_id)).subquery()

    def _counts(column) -> dict[str, int]:
        stmt = select(column, func.count()).select_from(base).group_by(column)
        return {row[0]: row[1] for row in db.execute(stmt)}

    day = func.date(base.c.valid_from).label("day")
    per_day = [
        {"day": str(row[0]), "count": row[1]}
        for row in db.execute(
            select(day, func.count()).select_from(base).group_by(day).order_by(day)
        )
    ]

    return {
        "total": db.execute(select(func.count()).select_from(base)).scalar_one(),
        "by_category": _counts(base.c.category),
        "by_source": _counts(base.c.source),
        "by_status": _counts(base.c.status),
        "per_day": per_day,
    }
