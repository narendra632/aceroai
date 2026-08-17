"""Cross-session memory: extract durable facts about the user from conversations,
embed them, store them in `profile_facts` (pgvector), and recall the most relevant
ones by semantic similarity.

Two guarantees keep this off the critical path:
- **Extraction** runs as a background task after the reply is delivered, in its
  own DB session, and swallows every error — it never delays or breaks a reply.
- **Recall** is best-effort: if embedding or search fails (e.g. quota), it returns
  no facts and the chat proceeds normally.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Sequence

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import llm, telemetry
from app.db.models import ProfileFact, User
from app.db.session import SessionLocal
from app.services import memory as svc
from app.services.memory import live

log = logging.getLogger(__name__)
timing = logging.getLogger("aceroai.timing")

_CATEGORIES = {"preference", "health", "work", "finance", "relationship", "other"}

_EXTRACT_SYSTEM = (
    "You extract durable, personal facts about the user from one conversation turn, "
    "to remember for future conversations. Capture only stable, useful facts an "
    "assistant should remember long-term: preferences, goals, work, health, "
    "relationships, finances. Ignore small talk, one-off logistics, and anything "
    "ephemeral. Do not repeat facts already known. Return ONLY a JSON array "
    '(possibly empty) of objects with keys "fact" (a short third-person statement), '
    '"category" (one of: preference, health, work, finance, relationship, other), '
    'and "confidence" (0-1). '
    # Phrasing consistency is not cosmetic — it is what makes a contradiction *findable*.
    # Two facts are compared by the distance between their embeddings, and the SUBJECT of
    # the sentence moves that distance as much as the claim does. Measured on real data:
    #
    #   "The user works at Infosys."  vs  "Narendra works at TCS."   -> 0.328
    #   "Narendra works at Infosys."  vs  "Narendra works at TCS."   -> 0.131
    #
    # Identical claim, 2.5x closer. At 0.328 the two employers looked unrelated and were
    # not even joined on the graph; at 0.131 they sit right on top of each other, which is
    # exactly the signal a conflict check needs. Drifting between "the user" and a name was
    # hiding real contradictions.
    "Always refer to the user the SAME way in every fact. Match the wording used in the "
    "known facts above; if there are none, write 'The user'. Never alternate between a "
    "name and a generic reference. "
    # The `replaces` key is what makes changed facts survive. A fact that CHANGED is by
    # construction near-identical in wording to the one it replaces, so the vector dedup
    # gate cannot tell them apart — only a reader of both can. The model is already
    # looking at both, so asking costs nothing.
    "If a new fact CONTRADICTS or UPDATES one of the known facts rather than being new "
    'information, add a "replaces" key whose value is the known fact\'s text copied '
    "EXACTLY. Use it only for a genuine change (a new job, a changed preference), never "
    "for a fact that merely restates something already known — restatements should simply "
    "be omitted. Output no prose, only the JSON array."
)


# --- recall (sync DB helper; call via run_in_threadpool with a precomputed vector) ---


def recall_facts(db: Session, user: User, query_vec: list[float], k: int) -> list[str]:
    """Return up to `k` active facts most similar to `query_vec`, closest first.

    `live()` comes from `services.memory` rather than being repeated here: a fact the user
    has forgotten must be unreachable from *every* path, and the surest way to guarantee
    that is for there to be only one definition of what "visible" means.
    """
    if k <= 0:
        return []
    stmt = (
        live(select(ProfileFact.fact))
        .where(
            ProfileFact.user_id == user.id,
            ProfileFact.status == "active",
            ProfileFact.embedding.isnot(None),
        )
        .order_by(ProfileFact.embedding.cosine_distance(query_vec))
        .limit(k)
    )
    return list(db.execute(stmt).scalars().all())


async def recall(db: Session, user: User, query_text: str, k: int | None = None) -> list[str]:
    """Best-effort semantic recall for the current message. Returns [] on any
    failure so a quota/network error never breaks the chat."""
    k = settings.memory_recall_k if k is None else k
    if k <= 0 or not query_text.strip():
        return []
    usage: dict = {}
    tl = telemetry.Timeline()
    try:
        t0 = time.perf_counter()
        vecs = await asyncio.wait_for(
            llm.embed([query_text], usage=usage), timeout=settings.memory_recall_timeout_s
        )
        t1 = time.perf_counter()
        facts = await run_in_threadpool(recall_facts, db, user, vecs[0], k)
        t2 = time.perf_counter()
        # Split the two halves: the embedding is a network round-trip, the search is
        # local pgvector. Knowing which dominates is the difference between "tune the
        # index" and "the provider is slow".
        timing.info(
            "recall embed=%.0fms pgvector=%.0fms facts=%d",
            (t1 - t0) * 1000,
            (t2 - t1) * 1000,
            len(facts),
        )
        # An embedding on EVERY message, previously billed and never counted.
        tl.stages.append(("embed", (t1 - t0) * 1000))
        tl.stages.append(("pgvector", (t2 - t1) * 1000))
        tl.annotate("pgvector", facts=len(facts))
        await telemetry.record(
            tl,
            user.id,
            "embed",
            provider=settings.embed_provider,
            model=settings.embed_model,
            usage=usage,
        )
        return facts
    except TimeoutError:
        timing.info(
            "recall timed out after %.1fs; answering without facts",
            settings.memory_recall_timeout_s,
        )
        return []
    except Exception:
        log.warning("memory recall failed; proceeding without facts", exc_info=True)
        return []


# --- extraction + storage (background; each helper owns its own DB session) ---


def _nearest_active(
    db: Session, user_id: uuid.UUID, vec: list[float]
) -> tuple[ProfileFact, float] | None:
    """The closest active fact to `vec`, with its distance. None if there are none."""
    row = db.execute(
        live(select(ProfileFact, ProfileFact.embedding.cosine_distance(vec).label("d")))
        .where(
            ProfileFact.user_id == user_id,
            ProfileFact.status == "active",
            ProfileFact.embedding.isnot(None),
        )
        .order_by(ProfileFact.embedding.cosine_distance(vec))
        .limit(1)
    ).first()
    return (row[0], float(row[1])) if row is not None else None


def _too_similar(db: Session, user_id: uuid.UUID, vec: list[float]) -> bool:
    nearest = _nearest_active(db, user_id, vec)
    return nearest is not None and nearest[1] < settings.memory_dedup_distance


def _normalise(text: str) -> str:
    """Collapse whitespace and case so the model's `replaces` echo can be matched against
    the stored text without demanding byte-identical output from a language model."""
    return " ".join((text or "").split()).casefold()


def _store(
    user_id: uuid.UUID,
    facts: list[dict],
    vectors: list[list[float]],
    source_ref: uuid.UUID | None = None,
) -> dict[str, int]:
    """Persist extracted facts, returning counts of what happened to each.

    Three outcomes, and telling them apart is the point:

    - **superseded** — the model flagged this as replacing a known fact, so the old belief
      is retired and linked to the new one. Without this a *changed* fact is indist-
      inguishable from a repeat by cosine distance alone (a new job is worded almost
      identically to the old one) and the newer truth would be silently discarded.
    - **skipped** — a genuine restatement, caught by the vector gate. This is the hard
      guarantee, and it is deliberately independent of anything the model said.
    - **stored** — actually new.
    """
    db = SessionLocal()
    counts = {"stored": 0, "superseded": 0, "skipped": 0}
    try:
        if db.get(User, user_id) is None:
            return counts

        # Only fetched when the model actually claims a replacement — the common case
        # costs no extra query.
        by_text: dict[str, ProfileFact] | None = None

        for fact, vec in zip(facts, vectors, strict=True):
            replaces = fact.get("replaces")
            if replaces:
                if by_text is None:
                    by_text = {
                        _normalise(row.fact): row
                        for row in svc.list_facts(db, user_id, limit=svc.LIST_MAX)
                    }
                target = by_text.get(_normalise(replaces))
                if target is not None:
                    svc.supersede_fact(
                        db,
                        user_id,
                        target.id,
                        fact=fact["fact"],
                        embedding=vec,
                        category=fact["category"],
                        confidence=fact["confidence"],
                        # The MODEL concluded this replacement, so it is inferred even
                        # when the fact it replaces had been confirmed by the user.
                        # Inheriting the old row's source would silently launder a guess
                        # into something the user appears to have stated.
                        source="inferred",
                    )
                    counts["superseded"] += 1
                    continue
                # The model named a fact we can't find. Ignore the hint rather than
                # guessing which one it meant, and fall through to the normal path.
                log.info("memory: `replaces` target not found, treating as new: %r", replaces)

            near = _nearest_active(db, user_id, vec)
            if near is not None and near[1] < settings.memory_dedup_distance:
                # Record WHAT was discarded, not just that something was. This branch
                # assumes the fact is a restatement, and distance alone provably cannot
                # tell a restatement from a change: measured, real restatements span
                # 0.020-0.028 and real changes span 0.029-0.118, which overlap. The
                # `replaces` hint above is what actually separates them, so if it ever
                # misses, a true correction dies here. Silently, until now — the counter
                # this used to increment left no way to ever discover it happened.
                log.info(
                    "memory: discarded as duplicate (distance %.3f) %r — nearest was %r",
                    near[1],
                    fact["fact"],
                    near[0].fact,
                )
                counts["skipped"] += 1
                continue
            db.add(
                ProfileFact(
                    user_id=user_id,
                    fact=fact["fact"],
                    category=fact["category"],
                    confidence=fact["confidence"],
                    source="inferred",
                    source_ref=source_ref,
                    status="active",
                    embedding=vec,
                )
            )
            counts["stored"] += 1
        db.commit()
        return counts
    finally:
        db.close()


def _parse_facts(raw: str) -> list[dict]:
    """Defensively pull a JSON array of facts out of the model's reply."""
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact", "")).strip()
        if not fact:
            continue
        category = str(item.get("category", "other")).strip().lower()
        if category not in _CATEGORIES:
            category = "other"
        try:
            confidence = float(item.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        replaces = str(item.get("replaces", "") or "").strip()
        out.append(
            {
                "fact": fact,
                "category": category,
                "confidence": min(max(confidence, 0.0), 1.0),
                # Empty string means "no claim" — kept as None so `_store` can test it
                # directly rather than distinguishing missing from blank.
                "replaces": replaces or None,
            }
        )
    return out


async def _extract(
    user_text: str, reply_text: str, known: Sequence[str], usage: dict | None = None
) -> list[dict]:
    known_block = "\n".join(f"- {k}" for k in known) or "(none yet)"
    user_msg = (
        f"Known facts:\n{known_block}\n\n"
        f"Conversation turn:\nUser: {user_text}\nAssistant: {reply_text}\n\n"
        "Extract only NEW durable facts as the JSON array."
    )
    raw = await llm.complete(
        [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        model=settings.model_memory or settings.model_chat,
        effort=settings.reasoning_effort_chat,
        usage=usage,
    )
    return _parse_facts(raw)


async def extract_and_store(
    user_id: uuid.UUID,
    user_text: str,
    reply_text: str,
    *,
    known: Sequence[str] = (),
    source_ref: uuid.UUID | None = None,
) -> None:
    """Best-effort: extract facts from a finished turn, embed, and store them.
    Never raises into the caller — the reply has already been delivered.

    `known` is the set of facts shown to the extractor so it doesn't propose things we
    already hold. **The caller passes the facts recall already retrieved for this message**
    — they are the ones most likely to be duplicated, they are already computed, and reusing
    them costs nothing. This used to load *every* active fact instead, which meant the
    extraction prompt grew forever: ~144 tokens at 11 facts, ~6,500 at 500. Bounded here it
    is constant.

    Narrowing this list is safe because it was never the real duplicate guarantee. That is
    `_too_similar`, which compares vectors against **every** stored fact regardless of what
    the prompt contained. `known` only makes the model's proposals tidier.

    `source_ref` is the message this turn came from, recorded so the user can ask "where did
    you get that?" and be shown the conversation.
    """
    tl = telemetry.Timeline()
    usage: dict = {}
    ok, error_type = True, None
    try:
        with tl.stage("extract"):
            facts = await _extract(user_text, reply_text, known, usage=usage)
        tl.annotate("extract", proposed=len(facts), known_shown=len(known))
        if not facts:
            return
        with tl.stage("embed_facts"):
            vectors = await llm.embed([f["fact"] for f in facts], usage=usage)
        counts = await run_in_threadpool(_store, user_id, facts, vectors, source_ref)
        tl.annotate("extract", **counts)
        if any(counts.values()):
            log.info(
                "memory: stored=%d superseded=%d skipped_duplicate=%d",
                counts["stored"],
                counts["superseded"],
                counts["skipped"],
            )
    except Exception as exc:
        ok, error_type = False, type(exc).__name__
        log.warning("memory extraction failed", exc_info=True)
    finally:
        # A second full model call fires after EVERY message to learn from it. It was
        # billed and completely uncounted — the largest invisible line in the bill.
        await telemetry.record(
            tl,
            user_id,
            "memory_extract",
            provider=settings.llm_provider,
            model=settings.model_memory or settings.model_chat,
            effort=settings.reasoning_effort_chat,
            usage=usage,
            ok=ok,
            error_type=error_type,
        )
