"""When something is written about a *theme* rather than a company.

A video titled *"Why defence manufacturing is the decade's trade"* names no company at all, so
the mention matcher sees nothing and the item is filed and forgotten. But the framework already
knows which chokepoints matter and which companies sit on each one — so a theme is not a dead
end, it is a lookup.

⚠ **This is where the framework earns its keep.** Without it the bottleneck list is a filing
cabinet: a place mappings are stored and occasionally read. With it the list becomes a routing
table, and attention paid to a theme becomes attention paid to a specific set of companies —
including ones already held, which is the half that matters most and the half nobody goes
looking for.

⚠ **Matching is deterministic and deliberately strict.** A theme is recognised only when at
least two distinctive words from a bottleneck's own name appear. One word is not a theme:
"power" appears in any article about anything, and a router that fired on it would report
every company in the book as newly relevant every day, which is the same as reporting nothing.

⚠ **A theme is never evidence.** It raises no proposal and changes no score. It answers one
question — *what am I exposed to that just got attention* — and the answer is a list to read,
not a reason to act.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import AbMapping, Candidate, Instrument, ListedCompany, SourceItem

#: Words that appear in bottleneck names and carry no discriminating power. ⚠ Without this,
#: "Manufacturing" alone would match eight different bottlenecks and "Infrastructure" four.
_WEAK = frozenset(
    {
        "and",
        "for",
        "the",
        "of",
        "advanced",
        "domestic",
        "access",
        "scale",
        "development",
        "applications",
        "alternatives",
        "self",
        "sufficiency",
        "ultra",
        "reliable",
        "private",
        "digital",
        "industrial",
        "skilled",
        "smart",
    }
)

#: How many distinctive words from a bottleneck's name must appear before it counts as the
#: subject. ⚠ Two, because one is an accident: an article about the electricity bill contains
#: "power", and a router firing on that would mark every grid holding as newly relevant.
MIN_WORDS = 2

#: A single-word bottleneck name can never reach two, so the few that are inherently
#: distinctive are allowed to match alone. ⚠ Kept explicit and short — a general rule for
#: "distinctive enough" is a rule nobody can audit.
STANDS_ALONE = frozenset({"nuclear", "osat", "cdmo", "crams", "biosimilars", "cybersecurity"})


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) > 2}


def vocabulary(spec: dict) -> dict[str, tuple[set[str], str]]:
    """Each bottleneck's distinctive words, and its name."""
    out: dict[str, tuple[set[str], str]] = {}
    for row in spec.get("bottlenecks", ()):
        distinctive = _words(row.get("name", "")) - _WEAK
        if distinctive:
            out[row["id"]] = (distinctive, row.get("name", ""))
    return out


def _unique_words(vocab: dict[str, tuple[set[str], str]]) -> dict[str, set[str]]:
    """Per bottleneck, the words no other bottleneck's name uses.

    ⚠ The rule that stops a theme matching its neighbour. *Solar Cell & Module Manufacturing*
    and *Battery Energy Storage & Cell Manufacturing* share "cell" and "manufacturing", so an
    article about solar modules matched both — and reporting a battery holding as newly
    relevant to a solar article is the routing table producing noise in the one place it is
    supposed to produce precision. A match must now include at least one word that belongs to
    that bottleneck alone.
    """
    seen: dict[str, int] = {}
    for words, _ in vocab.values():
        for word in words:
            seen[word] = seen.get(word, 0) + 1
    return {b_id: {word for word in words if seen[word] == 1} for b_id, (words, _) in vocab.items()}


def themes_in(text: str, spec: dict) -> list[str]:
    """Which bottlenecks this text is about. Usually none, which is the correct answer."""
    present = _words(text)
    vocab = vocabulary(spec)
    unique = _unique_words(vocab)

    found = []
    for b_id, (distinctive, _) in vocab.items():
        hits = distinctive & present
        if not hits:
            continue
        # A word this bottleneck alone uses has to be among them, or the match is really a
        # match on the vocabulary two bottlenecks happen to share.
        if not (hits & unique[b_id]):
            continue
        if len(hits) >= MIN_WORDS or (hits & STANDS_ALONE):
            found.append(b_id)
    return sorted(found)


@dataclass
class Exposure:
    """One theme that got attention, and what the book has sitting on it."""

    bottleneck_id: str
    name: str
    #: Companies already held or watched that sit on this bottleneck — **approved mappings
    #: only**, because an unapproved mapping is a claim nobody has agreed with yet and
    #: counting it as exposure would let a suggestion create the exposure it then explains.
    held: list[str] = field(default_factory=list)
    #: Companies in the research queue proposed for this bottleneck.
    queued: list[str] = field(default_factory=list)
    #: How many separate items touched this theme in the window.
    mentions: int = 0


def exposure_to(db: Session, bottleneck_ids: list[str], spec: dict) -> list[Exposure]:
    """What the book holds and what is queued on each of these bottlenecks."""
    if not bottleneck_ids:
        return []

    names = {b_id: name for b_id, (_, name) in vocabulary(spec).items()}

    mapped = db.execute(
        sa.select(AbMapping.b_bottleneck, Instrument.symbol)
        .join(Instrument, AbMapping.instrument_id == Instrument.id)
        .where(
            AbMapping.b_bottleneck.in_(bottleneck_ids),
            AbMapping.superseded_by_id.is_(None),
            AbMapping.approved_at.is_not(None),
            Instrument.deleted_at.is_(None),
        )
    ).all()

    queued = db.execute(
        sa.select(Candidate.proposed_bottleneck, ListedCompany.symbol)
        .join(ListedCompany, Candidate.listed_company_id == ListedCompany.id)
        .where(
            Candidate.proposed_bottleneck.in_(bottleneck_ids),
            Candidate.status.in_(("QUEUED", "ANALYSING")),
        )
    ).all()

    out = []
    for b_id in bottleneck_ids:
        out.append(
            Exposure(
                bottleneck_id=b_id,
                name=names.get(b_id, b_id),
                held=sorted({symbol for bottleneck, symbol in mapped if bottleneck == b_id}),
                queued=sorted({symbol for bottleneck, symbol in queued if bottleneck == b_id}),
            )
        )
    return out


def read_themes(title: str | None, body: str | None, spec: dict | None) -> list[str]:
    """Which themes a document is about, from its words alone.

    ⚠ **Pure, and called BEFORE the row is written.** A first version set this on the
    `SourceItem` after it had been flushed, and the append-only trigger refused the update —
    the guard working on its author again. A theme is part of what was read, not something
    discovered about it afterwards, so it belongs in the row from the start.

    ⚠ It lands in the extraction the item already carries rather than in a table of its own,
    so the reading always sits beside the words that produced it. A separate table would put
    them a join apart and, eventually, a join nobody does.
    """
    if spec is None:
        return []
    return themes_in(f"{title or ''}\n{body or ''}", spec)


def recent_themes(db: Session, spec: dict, *, days: int = 14, limit: int = 200) -> list[Exposure]:
    """Themes written about lately, ordered by how much attention each got.

    ⚠ Only themes the book is actually exposed to are returned. A theme nobody holds anything
    on is real news about the world and no news about this portfolio, and a list that included
    it would bury the ones that matter.
    """
    import datetime as dt

    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    rows = db.execute(
        sa.select(SourceItem.extraction)
        .where(
            SourceItem.fetched_at >= since,
            SourceItem.extraction.is_not(None),
        )
        .order_by(SourceItem.fetched_at.desc())
        .limit(limit)
    ).scalars()

    counts: dict[str, int] = {}
    for extraction in rows:
        for b_id in (extraction or {}).get("themes", []):
            counts[b_id] = counts.get(b_id, 0) + 1

    if not counts:
        return []

    exposures = exposure_to(db, sorted(counts), spec)
    for row in exposures:
        row.mentions = counts.get(row.bottleneck_id, 0)

    return sorted(
        [row for row in exposures if row.held or row.queued],
        key=lambda row: (-row.mentions, row.bottleneck_id),
    )


def instruments_on(db: Session, bottleneck_ids: list[str]) -> list[uuid.UUID]:
    """The instruments sitting on these bottlenecks, for a re-score.

    ⚠ Approved mappings only, for the same reason `Exposure.held` uses them: an unapproved
    mapping is a claim nobody has agreed with, and pulling a company forward on the strength
    of one would let the system choose what to look at by means of what it proposed.
    """
    if not bottleneck_ids:
        return []
    return list(
        db.execute(
            sa.select(AbMapping.instrument_id).where(
                AbMapping.b_bottleneck.in_(bottleneck_ids),
                AbMapping.superseded_by_id.is_(None),
                AbMapping.approved_at.is_not(None),
            )
        ).scalars()
    )
