"""Hybrid recall: find the facts that answer this message, not merely the facts that
concern this user.

**Why two rankers.** Recall used to be one query — the `MEMORY_RECALL_K` nearest facts by
cosine distance — and it returned exactly that many facts on every message, including
`"write a python function to reverse a list"`. That is not a tuning problem, it is what the
measurement says the signal can do:

    where do I work            best match 0.406   (Narendra works at TCS)
    hello                      best match 0.419
    explain TCP handshakes     best match 0.518

Every fact about one person sits in a narrow 0.30-0.58 band, and `"hello"` lands *closer*
than a genuine match for another query. Distance answers **"is this about the same
person?"**. It does not answer **"does this answer the question?"**. No threshold separates
`works at TCS` from `has sisters`, because on this axis they are not separated.

Postgres full-text search fails in the opposite direction — precise where vectors are vague
(`certifications` -> exactly the certification facts) and blind where vectors see
(`where do I work` needs meaning, not the word). Fusing two rankers that fail differently is
worth more than tuning either.

**How they are combined.** Not by averaging their scores: cosine distance runs 0.30-0.58
and `ts_rank` runs 0.00-0.10, so any weighting silently lets one dominate and needs
re-tuning whenever either distribution moves. Reciprocal Rank Fusion throws the magnitudes
away and fuses *positions*, which needs no normalisation:

    score(fact) = sum over rankers of 1 / (RRF_K + rank_in_that_ranker)

A fact found by both rankers scores about twice one found by a single ranker (~0.032 vs
~0.015). That cliff — agreement — is the relevance signal distance could not provide.

**What `ts_rank` is not.** It is not BM25: no inverse document frequency, no term-frequency
saturation, no length normalisation. Measured on real facts, a single-term query gives
*every* match the identical score 0.060793 — it behaves as a filter, not a ranker. That is
fine, because the filter is where the value is: RRF only needs a position, and "does this
fact contain the thing you asked about" is the position that matters. Recorded so nobody
later assumes a sophistication that is not there.
"""

import logging
import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ProfileFact, User
from app.services.memory import live

log = logging.getLogger(__name__)

# Where a fact came from. Shown to the user in the recall popover, because "both rankers
# agreed" and "one ranker guessed" are genuinely different claims about a fact.
BOTH = "both"
VECTOR = "vector"
LEXICAL = "lexical"


@dataclass(frozen=True)
class RecalledFact:
    id: uuid.UUID
    fact: str
    category: str
    #: BOTH / VECTOR / LEXICAL — which ranker(s) found it.
    via: str

    def as_dict(self) -> dict:
        return {"id": str(self.id), "fact": self.fact, "category": self.category, "via": self.via}


# Dropped before a term ever costs a database probe. Postgres would drop these itself
# inside `plainto_tsquery`, but an empty tsquery matches nothing and therefore measures a
# document frequency of ZERO — which would make "the" look like the rarest, most
# identifying word in the message. Removing them here avoids that trap entirely.
_STOP = frozenset(
    """a about above after again against all am an and any are aren as at be because been
    before being below between both but by can cannot could couldn did didn do does doesn
    doing don down during each few for from further had hadn has hasn have haven having he
    her here hers herself him himself his how i if in into is isn it its itself just me
    more most mustn my myself no nor not of off on once only or other ought our ours
    ourselves out over own same shan she should shouldn so some such than that the their
    theirs them themselves then there these they this those through to too under until up
    very was wasn we were weren what when where which while who whom why with won would
    wouldn you your yours yourself yourselves will shall may might must get got give tell
    know think want need like also make made take took come came go went see saw say said
    thing things something anything really quite still even ever never always""".split()
)

_WORD = re.compile(r"[a-z0-9][a-z0-9'\-]*")

_LIVE_SQL = "user_id = :uid AND deleted_at IS NULL AND status = 'active'"


def terms(message: str) -> list[str]:
    """Distinct content words of a message, in order of appearance."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _WORD.finditer(message.lower()):
        word = match.group(0).strip("-'")
        if len(word) < 2 or word in _STOP or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


def _document_frequency(db: Session, user_id: uuid.UUID, words: Sequence[str]) -> tuple[int, dict]:
    """How many live facts contain each word, plus the total number of live facts.

    One round trip, as a UNION ALL of per-word counts. Each branch is its own `@@` test, so
    each can use the partial GIN index from migration 010 — the alternative shape,
    `count(*) FILTER (...)` in a single aggregate, forces one full scan that rebuilds every
    row's tsvector and cannot use the index at all.
    """
    branches = [f"SELECT -1 AS i, count(*) AS n FROM profile_facts WHERE {_LIVE_SQL}"]
    params: dict = {"uid": user_id}
    for i, word in enumerate(words):
        branches.append(
            f"SELECT {i}, count(*) FROM profile_facts WHERE {_LIVE_SQL} "
            f"AND to_tsvector('english', fact) @@ plainto_tsquery('english', :w{i})"
        )
        params[f"w{i}"] = word
    rows = db.execute(text(" UNION ALL ".join(branches)), params).all()

    total = 0
    freq: dict[str, int] = {}
    for i, n in rows:
        if i < 0:
            total = int(n)
        else:
            freq[words[i]] = int(n)
    return total, freq


def choose_terms(db: Session, user_id: uuid.UUID, message: str) -> tuple[list[str], set[str]]:
    """The words the lexical ranker will actually search for, and which of them are rare
    enough to admit a fact on their own.

    Three filters, in order:

    1. **Drop words that match nothing** (document frequency 0). They cannot contribute a
       candidate, so spending one of the eight slots on them is pure loss.
    2. **Drop words that match almost everything** (above `lexical_max_df`). A word in most
       facts says nothing about *which* fact you want — this is the one thing IDF would
       have told us, applied by hand. It is also the only real cost risk: measured, a term
       present in every fact costs 219 ms at 20k facts because `ts_rank` scores every match
       before sorting. Not hypothetical — every fact begins with the user's name by design.
    3. **Keep the rarest `lexical_terms_max`.** A three-paragraph message carries ~50
       content words and the opening ones are rarely the informative ones; `dentist`
       identifies a fact and `week` does not. Taking the first eight would be arbitrary,
       and OR-ing fifty would match nearly the whole table.

    Only `lexical_df_terms_max` words are measured, longest first, when a message has more
    than that. Length is a stated proxy for rarity (Zipf), used *only* to decide which words
    get an exact measurement — never to rank them. Real messages sit well inside the cap.
    """
    words = terms(message)
    if not words:
        return [], set()
    if len(words) > settings.lexical_df_terms_max:
        words = sorted(words, key=len, reverse=True)[: settings.lexical_df_terms_max]

    total, freq = _document_frequency(db, user_id, words)
    if total == 0:
        return [], set()

    common_at = max(settings.lexical_df_min_docs, math.ceil(settings.lexical_max_df * total))
    rare_at = max(settings.lexical_rare_min_docs, math.ceil(settings.lexical_rare_df * total))

    usable = [w for w in words if 0 < freq[w] <= common_at]
    usable.sort(key=lambda w: (freq[w], -len(w)))
    usable = usable[: settings.lexical_terms_max]
    return usable, {w for w in usable if freq[w] <= rare_at}


def vector_rank(
    db: Session, user_id: uuid.UUID, query_vec: Sequence[float], limit: int
) -> list[tuple[RecalledFact, float]]:
    """The nearest live facts by meaning, closest first, each with its cosine distance.

    ⚠ The ordering is TOTAL, not just by distance. Two facts can sit at exactly the same
    cosine distance from a query — genuinely, not as a rounding artefact — and `ORDER BY
    distance LIMIT n` then returns whichever of them Postgres happened to scan first. Which
    rows survive the limit changes as the heap is rewritten by ordinary updates and vacuum,
    so the same question against unchanged data could recall different facts on consecutive
    calls, and nothing anywhere reported it.

    `created_at DESC` breaks the tie, because between two equally relevant memories the more
    recent one is the better answer. `id` follows it only to make the order total when even
    the timestamps match — rows written in one transaction share a `created_at`, since
    Postgres `now()` is transaction start time.
    """
    distance = ProfileFact.embedding.cosine_distance(list(query_vec)).label("d")
    stmt = (
        live(select(ProfileFact.id, ProfileFact.fact, ProfileFact.category, distance))
        .where(
            ProfileFact.user_id == user_id,
            ProfileFact.status == "active",
            ProfileFact.embedding.isnot(None),
        )
        .order_by(distance, ProfileFact.created_at.desc(), ProfileFact.id)
        .limit(limit)
    )
    return [
        (RecalledFact(row.id, row.fact, row.category, VECTOR), float(row.d))
        for row in db.execute(stmt)
    ]


def lexical_rank(
    db: Session,
    user_id: uuid.UUID,
    words: Sequence[str],
    rare: set[str],
    limit: int,
) -> list[tuple[RecalledFact, bool]]:
    """Live facts containing any of `words`, best first, each flagged with whether it was
    matched by a *rare* word.

    The query is an OR of individually sanitised terms. `plainto_tsquery` is applied to each
    word separately and the results are `||`-ed together, so no user text is ever
    interpolated into a tsquery — `to_tsquery` on raw input is both a syntax error waiting
    to happen and an injection surface. The OR also matters for recall: `plainto_tsquery`
    on a whole phrase produces AND, and `'work office'` as AND matched **zero** facts while
    `Narendra works at TCS` sat right there.

    The candidate set is capped *before* ranking, in a subquery, so `ts_rank` cost is
    bounded by a constant instead of by the size of memory. At a few hundred to a few
    thousand facts with the DF filter applied this never binds; it exists so a pathological
    corpus degrades in quality rather than in latency.
    """
    if not words:
        return []
    params: dict = {"uid": user_id, "cand": settings.lexical_candidate_max, "pool": limit}
    for i, word in enumerate(words):
        params[f"w{i}"] = word
    any_q = " || ".join(f"plainto_tsquery('english', :w{i})" for i in range(len(words)))
    rare_idx = [i for i, w in enumerate(words) if w in rare]
    if rare_idx:
        rare_q = " || ".join(f"plainto_tsquery('english', :w{i})" for i in rare_idx)
        rare_expr = f"(c.tsv @@ ({rare_q}))"
    else:
        rare_expr = "false"

    sql = text(
        f"""
        SELECT c.id, c.fact, c.category, {rare_expr} AS rare
        FROM (
            SELECT id, fact, category, to_tsvector('english', fact) AS tsv
            FROM profile_facts
            WHERE {_LIVE_SQL} AND to_tsvector('english', fact) @@ ({any_q})
            LIMIT :cand
        ) c
        ORDER BY ts_rank(c.tsv, ({any_q})) DESC
        LIMIT :pool
        """
    )
    return [
        (RecalledFact(row.id, row.fact, row.category, LEXICAL), bool(row.rare))
        for row in db.execute(sql, params)
    ]


def _fuse(vector_ids: list[uuid.UUID], lexical_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    """Reciprocal Rank Fusion over the two ranked id lists."""
    k = settings.rrf_k
    scores: dict[uuid.UUID, float] = {}
    for ids in (vector_ids, lexical_ids):
        for rank, fact_id in enumerate(ids, start=1):
            scores[fact_id] = scores.get(fact_id, 0.0) + 1.0 / (k + rank)
    return scores


def search(
    db: Session, user: User, message: str, query_vec: Sequence[float], k: int | None = None
) -> list[RecalledFact]:
    """Run both rankers, fuse them, and select the facts worth sending to the model.

    The selection rule, in one sentence: **keep everything both rankers found, then top up
    from each ranker alone, but only from facts that clear that ranker's own quality bar.**

        consensus (both)  ->  admitted, provided the vector ranker actually had an opinion
        vector-only       ->  distance <= vector_only_max_distance, at most vector_only_max
        lexical-only      ->  matched a rare word, at most lexical_only_max

    **Why consensus needs a distance bound at all.** The vector ranker does not "find"
    facts, it *ranks* them: `ORDER BY distance LIMIT 20` returns twenty rows whether or not
    any of them relate to the message. So membership of its pool is only evidence when the
    pool is a small slice of memory. Caught by a test — at 25 stored facts the pool is 80%
    of everything, so a single keyword hit landed a fact at distance **1.0** in the
    "both rankers agreed" lane, and the recall popover would have told the user exactly
    that. A fact the vector ranker placed as far away as it can be placed is not agreement.

    Facts in both pools but beyond `consensus_max_distance` are therefore *demoted* to the
    lexical lane rather than dropped: the keyword hit is still real evidence, so it is
    judged by the lexical gate (a rare word) instead of being waved through.

    Lexical-only admission is deliberate and was almost left out. An earlier draft treated
    the keyword ranker as confirmation only — it could promote a fact the vector ranker had
    already found but never introduce one. That inverts the evidence: a long, multi-topic
    message is exactly where the vector ranker is weakest (it averages five subjects into
    one point), so a fact named outright by a distinctive word can fall out of its pool. A
    hit on a rare word is *stronger* evidence than a mid-band distance, not weaker.

    Both top-ups are gated because agreement is the signal and a bare top-up is a guess.
    Neither is a quota: a message about nothing stored recalls nothing at all.

    Either ranker failing degrades to the other rather than failing the turn — a recall
    that returns fewer facts is a worse answer, a recall that raises is a broken chat.
    """
    k = settings.memory_recall_k if k is None else k
    if k <= 0:
        return []
    pool = max(settings.recall_pool, k)

    vector: list[tuple[RecalledFact, float]] = []
    lexical: list[tuple[RecalledFact, bool]] = []
    vector_ok = lexical_ok = True

    try:
        vector = vector_rank(db, user.id, query_vec, pool)
    except Exception:  # noqa: BLE001 - one ranker failing must not lose the other
        vector_ok = False
        log.warning("vector ranker failed; falling back to lexical only", exc_info=True)
    try:
        words, rare = choose_terms(db, user.id, message)
        lexical = lexical_rank(db, user.id, words, rare, pool)
    except Exception:  # noqa: BLE001
        lexical_ok = False
        log.warning("lexical ranker failed; falling back to vector only", exc_info=True)

    # A ranker that RAISED is not the same as a ranker that found nothing. Finding nothing
    # is a real answer ("no fact contains any of these words") and the selection rule
    # depends on it; raising means we have no opinion, so fall back to the surviving
    # ranker's own ordering rather than pretending it agreed with an empty list.
    if not lexical_ok:
        return [f for f, _ in vector[:k]]
    if not vector_ok:
        return [f for f, _ in lexical[:k]]

    distance = {f.id: d for f, d in vector}
    rare_hit = {f.id: r for f, r in lexical}
    by_id = {f.id: f for f, _ in vector} | {f.id: f for f, _ in lexical}
    vector_ids = [f.id for f, _ in vector]
    lexical_ids = [f.id for f, _ in lexical]
    fused = _fuse(vector_ids, lexical_ids)

    in_vector, in_lexical = set(vector_ids), set(lexical_ids)
    both = in_vector & in_lexical
    consensus = {i for i in both if distance.get(i, 1.0) <= settings.consensus_max_distance}
    # Each lane is disjoint from the others, so nothing can be selected twice. The demoted
    # facts (in both pools, but too far for the vector ranker's membership to mean
    # anything) join the lexical lane and face its gate.
    vector_lane = in_vector - in_lexical
    lexical_lane = (in_lexical - in_vector) | (both - consensus)

    def by_score(ids) -> list[uuid.UUID]:
        return sorted(ids, key=lambda i: fused[i], reverse=True)

    chosen: list[uuid.UUID] = list(consensus)
    chosen += by_score(
        i for i in vector_lane if distance.get(i, 1.0) <= settings.vector_only_max_distance
    )[: settings.vector_only_max]
    chosen += by_score(i for i in lexical_lane if rare_hit.get(i))[: settings.lexical_only_max]

    out: list[RecalledFact] = []
    for fact_id in by_score(chosen)[:k]:
        fact = by_id[fact_id]
        out.append(
            RecalledFact(
                fact.id, fact.fact, fact.category, BOTH if fact_id in consensus else fact.via
            )
        )
    return out
