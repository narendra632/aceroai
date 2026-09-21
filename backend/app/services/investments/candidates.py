"""Turning a name somebody mentioned into something you can decide about.

A candidate arrives as a company and a sentence. This takes it through the same four steps
every holding goes through, in the same order and with the same code:

1. **Where does it sit?** The model reads what sources said and names a bottleneck from the
   framework's own list. That is a *proposal* and scores nothing until a person agrees.
2. **What does it actually report?** Its annual filings are read and the figures stored beside
   the words they came from.
3. **Is it a good business, and is the price sensible?** Computed from those figures alone.
4. **What would stop it?** The gates, unchanged.

⚠ **Nothing here is a shortcut for a candidate.** It would be easy to score a company nobody
owns more loosely — fewer years, a guessed sector, a default multiple — and every one of those
shortcuts would make a new idea look better than an existing holding purely because less was
known about it. Missing stays missing, and a candidate with unread filings scores *unknown*
exactly as a holding would.

⚠ **Analysis is not following.** A candidate being analysed has its filings read once and its
price fetched once; a *followed* company joins the daily price loop for as long as it is kept.
The first costs a handful of requests, the second costs them every day — so they are separate
acts, and only the second is called promotion.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import httpx
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import AbMapping, Candidate, Instrument, ListedCompany, Mention
from app.services.investments import deduce, frameworks, fundamentals, pricing, reading, scoring
from app.services.marketdata import feed
from app.services.marketdata.http import ProviderError

log = logging.getLogger(__name__)

#: ⚠ How many candidates one run will analyse. Each costs a model call and several filing
#: fetches, and a queue that suddenly gained forty names would otherwise spend an evening's
#: whole budget on companies nobody has looked at yet.
MAX_PER_RUN = 4


@dataclass
class Analysis:
    """What was learned about one candidate, and what is still missing."""

    symbol: str
    name: str
    bottleneck_id: str | None = None
    bottleneck_why: str | None = None
    confidence: float = 0.0
    #: Filings actually read. ⚠ Zero is a real and common outcome — a small company may file
    #: nothing the parser recognises — and it is reported rather than hidden, because a score
    #: computed from nothing must never look like a low score.
    filings_read: int = 0
    quality_earned: Decimal | None = None
    quality_available: Decimal | None = None
    price: Decimal | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_scoreable(self) -> bool:
        return self.quality_available is not None and self.quality_available > 0


def _excerpts(db: Session, candidate: Candidate, limit: int = 6) -> list[str]:
    rows = db.execute(
        sa.select(Mention.claim_excerpt)
        .where(Mention.listed_company_id == candidate.listed_company_id)
        .order_by(Mention.created_at.desc())
        .limit(limit)
    ).scalars()
    return [row for row in rows if row]


def place(db: Session, candidate: Candidate, spec: dict, version_id: uuid.UUID) -> Analysis:
    """Step 1: work out where this company sits in the framework, and propose it.

    ⚠ The proposal is unapproved, and unapproved means it scores zero. That is the guard
    against a machine talking itself into believing a random small-cap is nationally
    strategic — and it applies to a company the model just met exactly as it applies to one
    from Narendra's own notes.
    """
    company = db.get(ListedCompany, candidate.listed_company_id)
    result = Analysis(symbol=company.symbol, name=company.name)

    about = deduce.describe(company.name, _excerpts(db, candidate))
    deduction = deduce.bottleneck_for(company.name, about, spec)
    result.confidence = deduction.confidence
    result.bottleneck_why = deduction.why

    if not deduction.is_usable:
        candidate.proposed_bottleneck = None
        result.notes.append(
            deduction.why or "no bottleneck could be identified with enough confidence"
        )
        db.flush()
        return result

    result.bottleneck_id = deduction.bottleneck_id
    candidate.proposed_bottleneck = deduction.bottleneck_id

    instrument = reading.identity_for(db, candidate)
    frameworks.propose_mapping(
        db,
        instrument,
        b_bottleneck=deduction.bottleneck_id,
        spec=spec,
        framework_version_id=version_id,
        proposed_by="AGENT",
        rationale=f"{deduction.why} (confidence {deduction.confidence:.0%}); from {about[:300]}",
    )
    db.flush()
    return result


def read_filings(
    db: Session, instrument: Instrument, result: Analysis, c: httpx.Client | None = None
) -> Analysis:
    """Step 2: read what the company itself reported."""
    try:
        ingested = fundamentals.sync_instrument(db, instrument, c=c)
        result.filings_read = ingested.filings_read
    except ProviderError as exc:
        # ⚠ An unreachable filing service is not an absent filing. Recorded as a note so the
        # score's incompleteness has a stated cause rather than looking like a bad company.
        result.notes.append(f"filings could not be read: {exc.reason}")
    return result


def price_once(
    db: Session, instrument: Instrument, result: Analysis, c: httpx.Client | None = None
) -> Analysis:
    """Step 3a: fetch one price, so the valuation half of the score has something to work on.

    ⚠ One price, not a history. A candidate does not need a curve — it needs to be comparable
    with a defensible multiple today — and a year of closes for every name anyone mentions is
    exactly the spend this design avoids.
    """
    try:
        feed.close_for(db, instrument, c=c)
    except ProviderError as exc:
        result.notes.append(f"no price could be fetched: {exc.reason}")

    mark = pricing.latest(db, [instrument.id]).get(instrument.id)
    result.price = mark.price if mark else None
    if result.price is None:
        result.notes.append("no price on record yet, so the valuation half cannot be scored")
    return result


def score(db: Session, instrument: Instrument, spec: dict, result: Analysis) -> Analysis:
    """Step 3b: how good the business is, and whether the price is sensible.

    ⚠ `earned` and `available` travel together. "6.0" means nothing on its own — six out of
    six is excellent and six out of ten is mediocre, and the difference is entirely whether
    the filings had been read.
    """
    quality = scoring.quality_score(db, instrument, spec)
    result.quality_earned = quality.earned
    result.quality_available = quality.available
    if quality.available < scoring.MIN_AVAILABLE_FOR_VERDICT:
        result.notes.append(
            f"only {quality.available} of 10 points could be computed — too little filed "
            f"data to judge this company yet"
        )
    return result


def analyse(
    db: Session,
    candidate: Candidate,
    spec: dict,
    version_id: uuid.UUID,
    c: httpx.Client | None = None,
) -> Analysis:
    """Take one candidate through all four steps.

    ⚠ Nothing is committed. The caller owns the transaction, so a failure halfway through a
    batch leaves no half-analysed company behind.
    """
    result = place(db, candidate, spec, version_id)
    instrument = (
        db.get(Instrument, candidate.instrument_id)
        if candidate.instrument_id
        else reading.identity_for(db, candidate)
    )

    read_filings(db, instrument, result, c)
    price_once(db, instrument, result, c)
    score(db, instrument, spec, result)

    candidate.status = "ANALYSING"
    candidate.reviewed_at = dt.datetime.now(dt.UTC)
    db.flush()
    return result


def pending(db: Session, limit: int = MAX_PER_RUN) -> list[Candidate]:
    """Queued candidates nothing has looked at yet, best-sourced first."""
    return list(
        db.execute(
            sa.select(Candidate)
            .where(Candidate.status == "QUEUED")
            .order_by(
                Candidate.best_trust_tier,
                Candidate.mention_count.desc(),
                Candidate.first_seen_at,
            )
            .limit(limit)
        ).scalars()
    )


def analyse_pending(db: Session, spec: dict, version_id: uuid.UUID) -> list[Analysis]:
    """Analyse the next few queued candidates, each isolated from the others' failures."""
    out: list[Analysis] = []
    for candidate in pending(db):
        try:
            out.append(analyse(db, candidate, spec, version_id))
        except Exception as exc:  # noqa: BLE001 - one bad candidate must not end the round
            log.warning("analysing a candidate failed: %s", type(exc).__name__)
            db.rollback()
    return out


def mapping_for(db: Session, instrument_id: uuid.UUID) -> AbMapping | None:
    return (
        db.execute(
            sa.select(AbMapping)
            .where(AbMapping.instrument_id == instrument_id, AbMapping.superseded_by_id.is_(None))
            .order_by(AbMapping.created_at.desc())
        )
        .scalars()
        .first()
    )
