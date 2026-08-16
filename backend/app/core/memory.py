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

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import llm
from app.db.models import ProfileFact, User
from app.db.session import SessionLocal

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
    'and "confidence" (0-1). Output no prose, only the JSON array.'
)


# --- recall (sync DB helper; call via run_in_threadpool with a precomputed vector) ---


def recall_facts(db: Session, user: User, query_vec: list[float], k: int) -> list[str]:
    """Return up to `k` active facts most similar to `query_vec`, closest first."""
    if k <= 0:
        return []
    stmt = (
        select(ProfileFact.fact)
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
    try:
        t0 = time.perf_counter()
        vecs = await asyncio.wait_for(
            llm.embed([query_text]), timeout=settings.memory_recall_timeout_s
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


def _load_active_facts(user_id: uuid.UUID) -> list[str]:
    db = SessionLocal()
    try:
        return list(
            db.execute(
                select(ProfileFact.fact).where(
                    ProfileFact.user_id == user_id, ProfileFact.status == "active"
                )
            )
            .scalars()
            .all()
        )
    finally:
        db.close()


def _too_similar(db: Session, user_id: uuid.UUID, vec: list[float]) -> bool:
    nearest = (
        db.execute(
            select(ProfileFact.embedding.cosine_distance(vec))
            .where(
                ProfileFact.user_id == user_id,
                ProfileFact.status == "active",
                ProfileFact.embedding.isnot(None),
            )
            .order_by(ProfileFact.embedding.cosine_distance(vec))
            .limit(1)
        )
        .scalars()
        .first()
    )
    return nearest is not None and nearest < settings.memory_dedup_distance


def _store(user_id: uuid.UUID, facts: list[dict], vectors: list[list[float]]) -> int:
    """Insert new facts with embeddings, skipping semantic duplicates. Returns the
    number actually stored."""
    db = SessionLocal()
    stored = 0
    try:
        if db.get(User, user_id) is None:
            return 0
        for fact, vec in zip(facts, vectors, strict=True):
            if _too_similar(db, user_id, vec):
                continue
            db.add(
                ProfileFact(
                    user_id=user_id,
                    fact=fact["fact"],
                    category=fact["category"],
                    confidence=fact["confidence"],
                    source="inferred",
                    status="active",
                    embedding=vec,
                )
            )
            stored += 1
        db.commit()
        return stored
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
        out.append(
            {"fact": fact, "category": category, "confidence": min(max(confidence, 0.0), 1.0)}
        )
    return out


async def _extract(user_text: str, reply_text: str, known: list[str]) -> list[dict]:
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
    )
    return _parse_facts(raw)


async def extract_and_store(user_id: uuid.UUID, user_text: str, reply_text: str) -> None:
    """Best-effort: extract facts from a finished turn, embed, and store them.
    Never raises into the caller — the reply has already been delivered."""
    try:
        known = await run_in_threadpool(_load_active_facts, user_id)
        facts = await _extract(user_text, reply_text, known)
        if not facts:
            return
        vectors = await llm.embed([f["fact"] for f in facts])
        stored = await run_in_threadpool(_store, user_id, facts, vectors)
        if stored:
            log.info("memory: stored %d new fact(s)", stored)
    except Exception:
        log.warning("memory extraction failed", exc_info=True)
