"""What the system reads, and everything it heard named.

Three jobs, and the order matters:

1. **Register** where information comes from, with a trust tier. Tier 1 is a filing or a
   regulator, tier 2 the press, tier 3 commentary — and a proposal resting *only* on tier 3
   fails its sourcing gate. A stock named on a channel joins the research queue, never the
   portfolio.
2. **Poll** each source and store what was published, once, with its words.
3. **Record every instrument named**, acted on or not.

⚠ **Step 3 is the one that cannot be added later.** Judge a channel on the ideas you acted on
and you are measuring your own filter rather than the channel: a source that named forty
companies, of which three were looked at and one worked, reads as 33% instead of 2.5%. The
skipped ideas are missing from the denominator and there is no way to reconstruct them
afterwards, so the row is written the moment the thing is said.

⚠ **Who was named is decided by code; which direction was meant is decided by the model.**
That split is deliberate and load-bearing. Matching is deterministic, so the denominator is
never at the mercy of a model that forgot a company — and the model is never allowed to *add*
an instrument, only to read a direction onto one the matcher already found. A model that could
introduce names could quietly invent the very mentions the attribution measure counts.

⚠ **Every judgement is formed before anything is written**, because `mentions` is append-only
in its utterance. The same lesson as `agent_runs`: a row opened and then corrected is a row
the trigger refuses.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal

import httpx
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core import llm
from app.db.models import (
    AbMapping,
    Candidate,
    Instrument,
    ListedCompany,
    Mention,
    Portfolio,
    Source,
    SourceItem,
    Transaction,
)
from app.services.errors import NotFound
from app.services.investments import frameworks, history, pricing, scoring, themes, watching
from app.services.investments import portfolio as pf
from app.services.marketdata import feeds, http, universe, webpage
from app.services.marketdata.http import ProviderError

log = logging.getLogger(__name__)

#: Tier 1 is a filing or a regulator; tier 2 the press; tier 3 commentary.
FILING, PRESS, COMMENTARY = 1, 2, 3

#: A stance is only ever asked of commentary. An exchange announcement has no direction — it
#: reports that something happened, and reading a bull case into "board meeting intimation"
#: would put noise straight into the attribution numbers.
STANCE_READ_FROM_TIER = PRESS

#: Source kinds that make a CLAIM about a company rather than filing paperwork on its own
#: behalf. Two things follow from being on this list, and both matter.
#:
#: ⚠ **Only these open a research-queue line.** Your own product brief says it plainly — *a
#: stock mentioned on a channel enters the research queue* — and the reason is arithmetic. A
#: single live poll of NSE's five feeds named 184 listed companies, of which 21 were one
#: asset manager's routine ETF notices. A company filing its own paperwork is not recommending
#: itself; treating it as a lead would put several hundred entries a day into a queue meant to
#: hold the handful of things worth a look, and the queue would be abandoned within a week.
#:
#: ⚠ **Only these record a mention of a company nobody follows.** The mention table exists to
#: be the survivorship-proof denominator for judging sources *that make calls*. The exchange
#: makes none, so counting its 184 daily names would add roughly 65,000 rows a year to measure
#: a source that never claimed anything. Filings about companies already followed are still
#: recorded in full — that is news about your own book.
CLAIMING_KINDS = frozenset({"RSS_NEWS", "YOUTUBE", "USER_DROP", "MACRO"})

#: Source kinds that have a feed to poll. ⚠ `USER_DROP` is deliberately absent: the inbox is
#: event-driven — it is read when you drop something in — and it has no feed to fetch. Without
#: this it was picked up by every polling round and reported "no adapter for this kind of
#: source" five times a day, which is how a run report stops being worth reading.
POLLABLE_KINDS = frozenset({"RSS_EXCHANGE", "RSS_NEWS", "YOUTUBE", "EDGAR", "MACRO"})

#: Below this many characters a symbol is too short to match safely. "ON", "IT" and "GO" are
#: all real tickers somewhere and all appear constantly in ordinary prose. This floor applies
#: to companies already held or watched — symbols you confirmed by following them.
MIN_SYMBOL_LEN = 3

#: ⚠ A higher floor for the 2,595 companies merely *listed*. The exchange carries 165 symbols
#: of three characters or fewer — ACC, ACE, BSE, BEL — and at that length a ticker in ordinary
#: uppercase text is far more often an abbreviation than a company. The asymmetry is
#: deliberate: a missed mention costs an idea, a false one corrupts the denominator the
#: attribution measure divides by, and nothing downstream can tell a false mention from a
#: real one.
MIN_DISCOVERY_SYMBOL_LEN = 4

#: A one-word company name has to be at least this long to be matched on. "Amal" and "ACC"
#: are real companies; their names are also strings that appear constantly in unrelated text.
MIN_SOLO_NAME = 6

#: Words that are company names AND ordinary English, where matching would produce far more
#: noise than signal. ⚠ Checked lower-cased against both single-word names and tickers, so
#: "Eternal Limited" and a sentence about eternal optimism do not collide. Kept short and
#: explicit: a long list quietly becomes a blind spot nobody can see the shape of.
AMBIGUOUS = frozenset(
    {
        "ace",
        "acc",
        "apex",
        "beta",
        "deep",
        "bang",
        "eternal",
        "antarctica",
        "midwest",
        "best",
        "bright",
        "capital",
        "career",
        "central",
        "century",
        "choice",
        "cosmic",
        "crown",
        "dynamic",
        "elegant",
        "empire",
        "excel",
        "focus",
        "force",
        "fortune",
        "future",
        "global",
        "golden",
        "grand",
        "growth",
        "heritage",
        "ideal",
        "impact",
        "india",
        "integra",
        "jump",
        "legacy",
        "liberty",
        "lotus",
        "magnum",
        "marathon",
        "master",
        "mega",
        "modern",
        "nova",
        "onward",
        "option",
        "orient",
        "panorama",
        "paramount",
        "pioneer",
        "premier",
        "prime",
        "pulse",
        "quest",
        "regency",
        "reliance",
        "revival",
        "rich",
        "rising",
        "royal",
        "sanguine",
        "select",
        "shine",
        "signal",
        "simple",
        "smart",
        "sovereign",
        "spark",
        "sterling",
        "summit",
        "supreme",
        "swadeshi",
        "titan",
        "trend",
        "trust",
        "unique",
        "united",
        "universal",
        "valiant",
        "venture",
        "victory",
        "vision",
        "vital",
        "zenith",
    }
)

#: The corporate form at the END of a name, which is registration rather than identity.
#:
#: ⚠ **Trailing only, and the list is deliberately short.** An earlier version stripped
#: "Industries", "Technology" and "India" wherever they appeared, which turned *Apar
#: Industries Limited* into `apar` — four characters, under the floor below, so Apar could
#: never have been matched by name at all. Those words are part of what the company is
#: called. Only the legal form is not.
_TRAILING_FORM = re.compile(
    r"[\s,.\-]*\b(limited|ltd|private|pvt|inc|plc|llp|corporation)\b\.?\s*$",
    re.IGNORECASE,
)

#: The shortest name worth matching on. Shorter than this and a company called "Rolex Rings"
#: starts matching every mention of a watch.
MIN_NAME_LEN = 5

#: What is allowed to sit between the words of a name in someone else's text: a space, a
#: hyphen, a dot, an ampersand. "Apar Industries" must still match "Apar-Industries".
_JOIN = r"[^A-Za-z0-9]{1,3}"

#: How many items one poll of one source will ingest. A first poll of a busy exchange feed
#: would otherwise write several hundred rows and run the stance pass over all of them.
MAX_ITEMS_PER_POLL = 60

#: The DB caps the excerpt at 1024; stay under it in code too so a long sentence truncates
#: cleanly here rather than failing a CHECK at flush time.
EXCERPT_CHARS = 900


class Unapproved(Exception):
    """A source exists but has not been approved, so nothing is read from it."""


@dataclass(frozen=True)
class Target:
    """One company the reader can recognise, and the spellings it goes by.

    ⚠ Either an instrument (something the portfolio already has an opinion about) or a listed
    company (something merely on the exchange), never both. Which one it is decides what a
    mention of it does: attach to a holding, or open a line in the research queue.
    """

    instrument_id: uuid.UUID | None
    listed_company_id: uuid.UUID | None
    symbol: str
    name: str
    spellings: tuple[str, ...]

    @property
    def is_known(self) -> bool:
        """Whether this is already held or watched, as opposed to merely listed."""
        return self.instrument_id is not None

    @property
    def key(self) -> str:
        """⚠ Identity for de-duplication within one item. A company can be reached by its
        name and by its ticker in the same sentence, and that is one mention, not two."""
        return f"{self.symbol}|{self.instrument_id or self.listed_company_id}"


@dataclass
class PollResult:
    source: str
    fetched: int = 0
    stored: int = 0
    mentions: int = 0
    #: ⚠ Recorded rather than raised. A feed that answered with nothing is not the same as a
    #: source that published nothing, and a poller that conflated them would turn a missed
    #: YouTube fetch into "this channel named no companies this week".
    silent: bool = False
    error: str | None = None
    names: list[str] = field(default_factory=list)
    #: Companies newly added to the research queue by this poll.
    discovered: list[str] = field(default_factory=list)
    #: Bottlenecks this round's reading was about, whether or not a company was named.
    themes: list[str] = field(default_factory=list)


# --- the register --------------------------------------------------------------------------


def register(
    db: Session,
    *,
    kind: str,
    name: str,
    handle: str,
    trust_tier: int,
    notes: str | None = None,
    approved: bool = False,
) -> Source:
    """Add a source, or return the one already registered under that handle.

    ⚠ `approved` defaults to False, and the default is the point. Adding a source changes what
    the system reads and therefore what it can be talked into; that is a decision the user
    makes, the same way they approve a framework mapping.
    """
    existing = db.execute(
        sa.select(Source).where(Source.kind == kind, Source.handle == handle)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = Source(
        id=uuid.uuid4(),
        kind=kind,
        name=name,
        handle=handle,
        trust_tier=trust_tier,
        notes=notes,
        approved_at=dt.datetime.now(dt.UTC) if approved else None,
    )
    db.add(row)
    db.flush()
    return row


def approve(db: Session, source: Source) -> Source:
    if source.approved_at is None:
        source.approved_at = dt.datetime.now(dt.UTC)
        db.flush()
    return source


def set_active(db: Session, source: Source, *, active: bool) -> Source:
    """Switch a source on or off. ⚠ Never deleted: a removed source would orphan every
    mention that cited it and silently rewrite the attribution history."""
    source.is_active = active
    db.flush()
    return source


def registered(
    db: Session, *, only_readable: bool = False, only_pollable: bool = False
) -> list[Source]:
    """Every registered source. `only_readable` drops the unapproved and switched-off;
    `only_pollable` also drops the ones with no feed to fetch."""
    q = sa.select(Source).where(Source.deleted_at.is_(None))
    if only_readable:
        q = q.where(Source.is_active.is_(True), Source.approved_at.is_not(None))
    if only_pollable:
        q = q.where(Source.kind.in_(POLLABLE_KINDS))
    return list(db.execute(q.order_by(Source.trust_tier, Source.name)).scalars())


# --- who was named -------------------------------------------------------------------------
#
# ⚠ **This scans an index, it does not sweep patterns.** With eleven tracked companies a
# regex each was fine. The vocabulary is now the exchange's whole equity list — 2,595
# companies — and 2,595 regexes against every item of every feed would be the slowest thing
# in the module by a wide margin. So names are looked up: the text is tokenised once and its
# word-runs are checked against a dictionary, which costs the length of the text rather than
# the size of the vocabulary.


def _normalise(text: str) -> str:
    """⚠ An ampersand is the word "and".

    The exchange lists TARIL as *Transformers **And** Rectifiers (India) Limited*; everyone
    who writes about it types *Transformers **&** Rectifiers*. Tokenised literally the two
    never meet, and the company is simply invisible to the reader — silently, because a name
    that fails to match looks exactly like a name that was never said.
    """
    return text.replace("&", " and ")


def _name_key(name: str) -> tuple[str, ...]:
    """A company name reduced to the words that identify it, in order.

    Strips the trailing legal form and nothing else, so *Apar Industries Limited* keeps both
    words that make it Apar Industries and not some other Apar.
    """
    core = _TRAILING_FORM.sub("", (name or "").strip())
    return tuple(word for word in re.split(r"[^A-Za-z0-9]+", _normalise(core).lower()) if word)


def _tokens(text: str) -> list[tuple[str, str, int]]:
    """Every word in the text as `(lowercase, as-written, where it starts)`.

    ⚠ The same splitter as `_name_key`, deliberately. A vocabulary tokenised one way and a
    text tokenised another would fail to match exactly the awkward names — *GE Vernova T&D* —
    that most need matching, and would do it silently.
    """
    # ⚠ Offsets are taken from the ORIGINAL text, not the normalised copy, so an excerpt
    # quotes what was actually written. `_normalise` only ever replaces one character with a
    # padded word, which shifts positions — hence the two are walked separately.
    out: list[tuple[str, str, int]] = []
    for m in re.finditer(r"[A-Za-z0-9]+|&", text):
        written = m.group(0)
        out.append(("and" if written == "&" else written.lower(), written, m.start()))
    return out


def _sentence_around(text: str, index: int) -> str:
    start = max(text.rfind(". ", 0, index), text.rfind(chr(10), 0, index)) + 1
    end = text.find(". ", index)
    end = len(text) if end == -1 else end + 1
    return text[start:end].strip()[:EXCERPT_CHARS]


@dataclass
class Vocabulary:
    """Every name the reader can recognise, indexed for lookup rather than for scanning."""

    #: word-tuple → entry. Multi-word names live here, and single-word ones that pass the floor.
    by_name: dict[tuple[str, ...], Target] = field(default_factory=dict)
    #: exact uppercase symbol → entry.
    by_symbol: dict[str, Target] = field(default_factory=dict)
    #: Symbols carrying punctuation ("GVT&D") cannot be found by word lookup, so the few that
    #: exist keep a pattern each.
    odd_symbols: list[tuple[re.Pattern, Target]] = field(default_factory=list)
    #: ⚠ Every symbol the portfolio already follows, whatever its name length. A held company
    #: and its entry on the exchange's list are the same company under two spellings — the
    #: instrument is "Kaynes Technology", the list says "Kaynes Technology India Limited" — and
    #: longest-match-wins would pick the listed one. A filing about something already owned
    #: would then open a research-queue line for a company sitting in the book.
    known_symbols: dict[str, Target] = field(default_factory=dict)
    longest: int = 1

    def resolve(self, target: Target) -> Target:
        """The held instrument for this company where there is one, else the target itself."""
        if target.is_known:
            return target
        return self.known_symbols.get(target.symbol.upper(), target)

    def add(self, target: Target, *, min_symbol: int) -> None:
        symbol = target.symbol.strip()
        if target.is_known and symbol:
            self.known_symbols[symbol.upper()] = target
        # ⚠ The ambiguity guard applies to DISCOVERY only. "ACE" is both a listed company and
        # a word about a good quarter, so it must not be plucked out of the wider exchange —
        # but if you follow Action Construction Equipment, you chose that ticker, and a system
        # that refused to recognise news about your own holding would be protecting you from
        # your own decision.
        ambiguous = not target.is_known and symbol.lower() in AMBIGUOUS
        if len(symbol) >= min_symbol and not ambiguous:
            if symbol.isalnum():
                self.by_symbol.setdefault(symbol.upper(), target)
            else:
                self.odd_symbols.append(
                    (
                        re.compile(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])"),
                        target,
                    )
                )

        for spelling in target.spellings:
            words = _name_key(spelling)
            if not words:
                continue
            # ⚠ A one-word name has to clear a height and not be an ordinary word. "Amal
            # Limited" and "ACC Limited" are real companies whose names appear constantly in
            # prose that has nothing to do with them, and a false mention is worse than a
            # missed one: it enters the denominator the attribution measure divides by, and
            # nothing downstream can tell it from a real one.
            if len(words) == 1 and not target.is_known:
                if len(words[0]) < MIN_SOLO_NAME or words[0] in AMBIGUOUS:
                    continue
            if sum(len(w) for w in words) < MIN_NAME_LEN:
                continue
            self.by_name.setdefault(words, target)
            self.longest = max(self.longest, len(words))


def _known(db: Session) -> list[Target]:
    """The companies the portfolio already has an opinion about — held or watched.

    ⚠ Indian equities only. A mention of "Bitcoin" in a video is not an idea about an
    instrument in the sense this table measures, and a crypto ticker like `ETH` inside prose
    would match constantly.
    """
    rows = db.execute(
        sa.select(Instrument).where(
            Instrument.deleted_at.is_(None),
            Instrument.is_tracked.is_(True),
            Instrument.asset_class == "EQUITY_IN",
        )
    ).scalars()
    return [
        Target(
            instrument_id=row.id,
            listed_company_id=None,
            symbol=(row.symbol or "").strip(),
            name=row.name,
            spellings=tuple([row.name, *(row.aliases or [])]),
        )
        for row in rows
    ]


def _listed(db: Session) -> list[Target]:
    """Every other company on the exchange — the half that makes discovery possible."""
    rows = db.execute(sa.select(ListedCompany).where(ListedCompany.delisted_at.is_(None))).scalars()
    return [
        Target(
            instrument_id=None,
            listed_company_id=row.id,
            symbol=(row.symbol or "").strip(),
            name=row.name,
            spellings=(row.name,),
        )
        for row in rows
    ]


def vocabulary(db: Session) -> Vocabulary:
    """What the reader can recognise: what you already follow, then the whole exchange.

    ⚠ **Order matters and is load-bearing.** A company you hold is added first, so a mention
    of it resolves to *your holding* rather than to an anonymous listed name. Reversed, a
    filing about Apar would create a research-queue entry for a company already in the book.
    """
    vocab = Vocabulary()
    for target in _known(db):
        # A symbol you already follow is one you confirmed, so the shorter floor applies.
        vocab.add(target, min_symbol=MIN_SYMBOL_LEN)
    for target in _listed(db):
        vocab.add(target, min_symbol=MIN_DISCOVERY_SYMBOL_LEN)
    return vocab


def named_in(text: str, vocab: Vocabulary) -> list[tuple[Target, str]]:
    """Every company the text names, with the sentence that named it.

    Longest name first at each position, so *Solar Industries India* is never read as some
    other company called *Solar*.
    """
    tokens = _tokens(text)
    found: dict[str, tuple[Target, str]] = {}

    index = 0
    while index < len(tokens):
        step = 1
        for width in range(min(vocab.longest, len(tokens) - index), 0, -1):
            words = tuple(word for word, _, _ in tokens[index : index + width])
            hit = vocab.by_name.get(words)
            if hit is not None:
                target = vocab.resolve(hit)
                found.setdefault(target.key, (target, _sentence_around(text, tokens[index][2])))
                step = width
                break
        index += step

    # ⚠ Case-SENSITIVE on the symbol, and a separate pass because a ticker is not a word in
    # the sentence. Lower-cased, "apar" and "rolex" are ordinary English; as tickers they are
    # shouted, and requiring the shout removes most of the false positives a symbol match
    # would otherwise produce.
    for _, written, at in tokens:
        hit = vocab.by_symbol.get(written)
        if hit is not None and written.isupper():
            target = vocab.resolve(hit)
            found.setdefault(target.key, (target, _sentence_around(text, at)))

    for pattern, hit in vocab.odd_symbols:
        match = pattern.search(text)
        if match:
            target = vocab.resolve(hit)
            found.setdefault(target.key, (target, _sentence_around(text, match.start())))

    return list(found.values())


# --- the vocabulary, kept current ------------------------------------------------------------


def sync_universe(db: Session, c: httpx.Client | None = None) -> dict:
    """Refresh the exchange's equity list.

    ⚠ **A company that has left the list is marked delisted, never deleted.** It was still
    named by sources while it was listed, and removing it would make those mentions
    unresolvable — quietly shrinking the denominator the attribution measure divides by, in
    the one direction that flatters every source.
    """
    listed = universe.fetch(c)
    now = dt.datetime.now(dt.UTC)

    existing = {
        (row.exchange, row.symbol): row for row in db.execute(sa.select(ListedCompany)).scalars()
    }
    added = updated = 0
    for entry in listed:
        row = existing.pop(("NSE", entry.symbol), None)
        if row is None:
            db.add(
                ListedCompany(
                    id=uuid.uuid4(),
                    symbol=entry.symbol,
                    exchange="NSE",
                    name=entry.name,
                    series=entry.series,
                    isin=entry.isin,
                    listed_on=entry.listed_on,
                    refreshed_at=now,
                )
            )
            added += 1
        else:
            if row.name != entry.name or row.delisted_at is not None:
                updated += 1
            row.name = entry.name
            row.series = entry.series
            row.isin = entry.isin or row.isin
            row.delisted_at = None
            row.refreshed_at = now

    gone = 0
    for row in existing.values():
        if row.delisted_at is None:
            row.delisted_at = now
            gone += 1

    db.flush()
    return {"listed": len(listed), "added": added, "updated": updated, "delisted": gone}


# --- the research queue ------------------------------------------------------------------
#
# ⚠ A candidate is a company something NAMED. It is deliberately not priced and not scored
# until someone decides it is worth the spend — pricing every name ever mentioned would put
# the API allowance and the disk budget behind companies nobody has chosen to care about.


def note_candidate(
    db: Session,
    target: Target,
    mention: Mention,
    source: Source,
    *,
    when: dt.datetime | None = None,
) -> bool:
    """Open or refresh a line in the research queue. True if this is the first sighting.

    ⚠ A candidate already dismissed is **not** silently reopened. Being named again is not new
    information — a channel repeating itself is the most ordinary thing a channel does — and a
    queue that resurrected everything you refused would train you to stop refusing. Its count
    and its date still move, so a review can see it is being pushed.
    """
    when = when or dt.datetime.now(dt.UTC)
    row = db.execute(
        sa.select(Candidate).where(Candidate.listed_company_id == target.listed_company_id)
    ).scalar_one_or_none()

    if row is not None:
        row.mention_count += 1
        row.last_seen_at = when
        row.best_trust_tier = min(row.best_trust_tier, source.trust_tier)
        db.flush()
        return False

    db.add(
        Candidate(
            id=uuid.uuid4(),
            listed_company_id=target.listed_company_id,
            status="QUEUED",
            first_mention_id=mention.id,
            first_seen_at=when,
            last_seen_at=when,
            mention_count=1,
            best_trust_tier=source.trust_tier,
        )
    )
    db.flush()
    return True


@dataclass(frozen=True)
class QueueLine:
    """One company waiting to be looked at."""

    id: uuid.UUID
    symbol: str
    name: str
    status: str
    mention_count: int
    best_trust_tier: int
    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    age_days: int
    named_by: str | None
    stance: str | None
    excerpt: str | None
    proposed_bottleneck: str | None
    dismissed_reason: str | None
    #: Filled once the candidate has been analysed. ⚠ `quality_earned` and `quality_available`
    #: travel together and must be SHOWN together: "4" means nothing on its own, because four
    #: out of four is excellent and four out of ten is mediocre, and the difference is entirely
    #: whether the filings had been read.
    quality_earned: Decimal | None = None
    quality_available: Decimal | None = None
    price: Decimal | None = None
    bottleneck_name: str | None = None
    #: Why the model placed it where it did, in its own words — so a wrong placement can be
    #: seen to be wrong rather than merely doubted.
    bottleneck_why: str | None = None


def queue(db: Session, *, statuses: tuple[str, ...] = ("QUEUED", "ANALYSING")) -> list[QueueLine]:
    """The research queue, the ones pushed hardest first.

    ⚠ Ordered by how good the best source was and then by how often it has been named — not by
    date. A company three sources keep returning to is a different proposition from one named
    once in passing, and newest-first would bury it under today's noise.
    """
    rows = db.execute(
        sa.select(Candidate, ListedCompany, Mention, SourceItem, Source)
        .join(ListedCompany, Candidate.listed_company_id == ListedCompany.id)
        .join(Mention, Candidate.first_mention_id == Mention.id, isouter=True)
        .join(SourceItem, Mention.source_item_id == SourceItem.id, isouter=True)
        .join(Source, SourceItem.source_id == Source.id, isouter=True)
        .where(Candidate.status.in_(statuses))
        .order_by(
            Candidate.best_trust_tier,
            Candidate.mention_count.desc(),
            Candidate.last_seen_at.desc(),
        )
    ).all()

    today = dt.datetime.now(dt.UTC)
    # ⚠ Scored only for candidates something has actually looked at. Running the quality score
    # over every queued name would read filings nobody has asked about, which is the spend the
    # whole candidate/instrument split exists to avoid.
    analysed = {
        row.id: row
        for row in (
            db.execute(
                sa.select(Instrument).where(
                    Instrument.id.in_(
                        [c.instrument_id for c, *_ in rows if c.instrument_id is not None]
                    )
                )
            ).scalars()
        )
    }
    # ⚠ The APPROVED framework, and a queue that cannot find one simply shows no scores
    # rather than falling back to an unapproved proposal — which would let a suggested
    # bottleneck take effect before anyone agreed to it.
    spec = None
    if analysed:
        try:
            spec = frameworks.current(db).spec
        except NotFound:
            spec = None

    def _scored(candidate: Candidate) -> tuple:
        instrument = analysed.get(candidate.instrument_id)
        if instrument is None or spec is None:
            return (None, None, None)
        quality = scoring.quality_score(db, instrument, spec)
        mark = pricing.latest(db, [instrument.id]).get(instrument.id)
        return (quality.earned, quality.available, mark.price if mark else None)

    out: list[QueueLine] = []
    for candidate, company, mention, item, source in rows:
        earned, available, price = _scored(candidate)
        detail = (
            frameworks.bottleneck(spec, candidate.proposed_bottleneck)
            if spec and candidate.proposed_bottleneck
            else None
        )
        out.append(
            QueueLine(
                id=candidate.id,
                symbol=company.symbol,
                name=company.name,
                status=candidate.status,
                mention_count=candidate.mention_count,
                best_trust_tier=candidate.best_trust_tier,
                first_seen_at=candidate.first_seen_at,
                last_seen_at=candidate.last_seen_at,
                age_days=(today - candidate.first_seen_at).days,
                named_by=source.name if source else (item.source if item else None),
                stance=mention.stance if mention else None,
                excerpt=mention.claim_excerpt if mention else None,
                proposed_bottleneck=candidate.proposed_bottleneck,
                dismissed_reason=candidate.dismissed_reason,
                quality_earned=earned,
                quality_available=available,
                price=price,
                bottleneck_name=detail.get("name") if detail else None,
                bottleneck_why=_mapping_rationale(db, candidate),
            )
        )
    return out


def _mapping_rationale(db: Session, candidate: Candidate) -> str | None:
    """Why the model placed this company where it did, in its own words."""
    if candidate.instrument_id is None:
        return None
    return db.execute(
        sa.select(AbMapping.rationale)
        .where(
            AbMapping.instrument_id == candidate.instrument_id,
            AbMapping.superseded_by_id.is_(None),
        )
        .order_by(AbMapping.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def identity_for(
    db: Session, candidate: Candidate, *, sector: str | None = None, tracked: bool = False
) -> Instrument:
    """The instrument record a candidate needs before anything can be read about it.

    ⚠ **`tracked` is the spending decision, and it defaults to False.** A company being
    analysed has its filings read once and a price fetched once; a *tracked* company joins the
    daily price loop for as long as it is followed. Analysing therefore costs a handful of
    requests, and following costs them every day — which is why they are separate acts.
    """
    company = db.get(ListedCompany, candidate.listed_company_id)
    existing = db.execute(
        sa.select(Instrument).where(
            Instrument.symbol == company.symbol,
            Instrument.exchange == company.exchange,
            Instrument.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = Instrument(
            id=uuid.uuid4(),
            symbol=company.symbol,
            exchange=company.exchange,
            isin=company.isin,
            name=company.name,
            asset_class="EQUITY_IN",
            currency="INR",
            sector=sector,
            is_tracked=tracked,
        )
        db.add(existing)
        db.flush()
    elif tracked:
        existing.is_tracked = True

    candidate.instrument_id = existing.id
    db.flush()
    return existing


def promote(db: Session, candidate: Candidate, *, sector: str | None = None) -> Instrument:
    """Start following a candidate: it joins the daily price loop and is scored from then on.

    ⚠ **This is the moment the meter starts**, which is why it is an explicit act rather than
    something the queue does on its own.
    """
    instrument = identity_for(db, candidate, sector=sector, tracked=True)
    candidate.status = "PROMOTED"
    candidate.reviewed_at = dt.datetime.now(dt.UTC)
    db.flush()
    return instrument


def dismiss(db: Session, candidate: Candidate, reason: str) -> Candidate:
    """Drop a candidate, with a reason the database insists on.

    ⚠ The reason is the data. It is the only record of what kinds of idea keep being refused,
    and without it a tidied queue is indistinguishable from one that was never filled.
    """
    if not (reason or "").strip():
        raise ValueError("dismissing a candidate needs a reason")
    candidate.status = "DISMISSED"
    candidate.dismissed_reason = reason.strip()
    candidate.reviewed_at = dt.datetime.now(dt.UTC)
    db.flush()
    return candidate


# --- the inbox ------------------------------------------------------------------------------
#
# ⚠ **You are a source, and you are measured like one.** A link from a friend, a video, a
# note — all of it is recorded the same way a channel is, with the same mention rows behind
# it. In six months that answers a question nothing else can: do the tips you act on beat the
# exchange feed you ignore?


#: Two registered sources, because the tier is a property of the source and a drop can be
#: either. ⚠ A page from the exchange or a regulator is a filing; a page from anywhere else is
#: a report of one. Splitting them keeps the sourcing gate meaningful and, incidentally,
#: measures your official drops separately from your tips.
INBOX_HANDLE = "inbox"
INBOX_OFFICIAL_HANDLE = "inbox-official"

#: ⚠ Above this many companies in one item, it is an index page rather than an article.
#: Measured: a live Economic Times "stocks in news" listing named **32** on 21 Sep 2026. A
#: drop naming thirty companies is not a lead about thirty companies, and queueing them would
#: bury the handful that were actually argued for under a page of navigation.
MAX_NAMES_PER_DROP = 12


@dataclass
class DropResult:
    """What came of something you dropped in."""

    stored: bool
    title: str
    url: str | None
    named: list[str] = field(default_factory=list)
    discovered: list[str] = field(default_factory=list)
    already_followed: list[str] = field(default_factory=list)
    #: ⚠ Why nothing happened, when nothing happened. A silent no-op is the one outcome an
    #: inbox must never have — the user would go on dropping things into a void.
    note: str | None = None
    trust_tier: int = PRESS


def inbox_source(db: Session, *, official: bool) -> Source:
    """The register entry a drop is filed under. Approved on sight: you dropping it is the
    approval, which is the whole difference between your inbox and a channel."""
    return register(
        db,
        kind="USER_DROP",
        name="You (from a filing)" if official else "You",
        handle=INBOX_OFFICIAL_HANDLE if official else INBOX_HANDLE,
        trust_tier=FILING if official else PRESS,
        notes=(
            "Pages you dropped in that came from an exchange or a regulator."
            if official
            else "Links, videos and notes you dropped in yourself."
        ),
        approved=True,
    )


def drop(
    db: Session,
    *,
    url: str | None = None,
    text: str | None = None,
    c: httpx.Client | None = None,
) -> DropResult:
    """Read something you dropped in, and file it against the companies it names.

    ⚠ Nothing is committed here; the caller owns the transaction.
    """
    url = (url or "").strip() or None
    text = (text or "").strip() or None
    if not url and not text:
        return DropResult(stored=False, title="", url=None, note="there was nothing to read")

    title = (text or "")[:120]
    official = False

    if url:
        try:
            page = (
                webpage.youtube(url, c)
                if webpage.video_id(url) is not None
                else webpage.fetch(url, c)
            )
        except ProviderError as exc:
            return DropResult(stored=False, title=url, url=url, note=exc.reason)
        if page.is_thin and not text:
            # ⚠ "Nothing was read" is not "nobody was named", and a page needing JavaScript
            # produces exactly the same empty result as a page about nothing.
            return DropResult(
                stored=False,
                title=page.title,
                url=page.url,
                note="that page gave almost no text — it may need a browser to render",
            )
        title = page.title
        official = page.is_official
        text = f"{page.text}\n{text}" if text else page.text

    source = inbox_source(db, official=official)
    vocab = vocabulary(db)
    found = named_in(text, vocab)

    if len(found) > MAX_NAMES_PER_DROP:
        return DropResult(
            stored=False,
            title=title,
            url=url,
            trust_tier=source.trust_tier,
            named=sorted({target.symbol for target, _ in found}),
            note=(
                f"that names {len(found)} companies, so it reads like a listing page rather "
                f"than an argument about one — nothing was filed. Drop a specific article."
            ),
        )

    external_id = url or hashlib.sha256(text.encode()).hexdigest()[:32]
    if _already_seen(db, source, [external_id]):
        return DropResult(
            stored=False,
            title=title,
            url=url,
            trust_tier=source.trust_tier,
            note="that one is already filed",
        )

    stances = stances_for(text, [target.symbol for target, _ in found]) if found else {}

    now = dt.datetime.now(dt.UTC)
    item = SourceItem(
        id=uuid.uuid4(),
        kind="USER_DROP",
        instrument_id=(
            found[0][0].instrument_id if len(found) == 1 and found[0][0].is_known else None
        ),
        source_id=source.id,
        source=source.name,
        external_id=external_id,
        url=url,
        title=title[:500],
        published_at=now,
        fetched_at=now,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        excerpt=text[:2000],
        extraction={"feed": "inbox", "named": [t.symbol for t, _ in found]},
    )
    db.add(item)
    db.flush()

    result = DropResult(stored=True, title=title, url=url, trust_tier=source.trust_tier)
    for target, excerpt in found:
        mention = Mention(
            id=uuid.uuid4(),
            source_item_id=item.id,
            instrument_id=target.instrument_id,
            listed_company_id=target.listed_company_id,
            stance=stances.get(target.symbol, "MENTION_ONLY"),
            claim_excerpt=excerpt,
        )
        db.add(mention)
        db.flush()
        result.named.append(target.symbol)
        if target.is_known:
            result.already_followed.append(target.symbol)
        elif note_candidate(db, target, mention, source, when=now):
            result.discovered.append(target.symbol)

    source.last_polled_at = now
    db.flush()
    return result


# --- which direction was meant --------------------------------------------------------------

_STANCE_PROMPT = """You are reading one piece of investment commentary.

Below is its text, and a list of companies that were definitely named in it. For EACH company
in the list, say which direction the piece takes on it.

  BULL         - argues the company is attractive, undervalued, or worth buying
  BEAR         - argues against it: overvalued, deteriorating, worth selling or avoiding
  NEUTRAL      - discusses it with a view but takes no side
  MENTION_ONLY - names it in passing, as an example or comparison, with no view at all

Rules:
- Answer for every company in the list and for NO other company. Do not add names.
- When the text does not clearly take a side, MENTION_ONLY is the correct answer. It is by
  far the most common one, and guessing a direction is worse than reporting none.

Reply with JSON only: {"stances": [{"symbol": "XYZ", "stance": "BULL"}]}"""

_VALID_STANCES = {"BULL", "BEAR", "NEUTRAL", "MENTION_ONLY"}


async def _ask_stances(text: str, symbols: list[str]) -> dict[str, str]:
    reply = await llm.complete(
        [
            {"role": "system", "content": _STANCE_PROMPT},
            {
                "role": "user",
                "content": f"Companies named: {', '.join(symbols)}\n\nText:\n{text}",
            },
        ],
        effort="low",
    )
    body = reply[reply.find("{") : reply.rfind("}") + 1]
    parsed = json.loads(body)
    return {
        str(row.get("symbol", "")).upper(): str(row.get("stance", "")).upper()
        for row in parsed.get("stances", [])
    }


def stances_for(text: str, symbols: list[str]) -> dict[str, str]:
    """Read a direction onto each named company. Anything unreadable is `MENTION_ONLY`.

    ⚠ The answer is **filtered back down to the symbols that were passed in**. A model that
    could introduce a name would be inventing the mentions the attribution measure counts, and
    an invented mention is indistinguishable from a real one once written.

    ⚠ A failed or malformed model call is not an error here. The mention still gets written,
    with no direction claimed — the denominator matters more than the direction, and losing
    the row to save the stance would be exactly backwards.
    """
    asked = {s.upper() for s in symbols}
    try:
        answered = asyncio.run(_ask_stances(text, symbols))
    except Exception as exc:  # noqa: BLE001 - any provider or parse failure lands here
        log.warning(
            "stance read failed (%s); recording mentions without a direction", type(exc).__name__
        )
        answered = {}

    return {
        symbol: answered.get(symbol) if answered.get(symbol) in _VALID_STANCES else "MENTION_ONLY"
        for symbol in asked
    }


# --- polling -------------------------------------------------------------------------------


def _fetch(source: Source, c: httpx.Client | None) -> list[feeds.Item]:
    if source.kind == "YOUTUBE":
        return feeds.youtube_uploads(source.handle, c)
    if source.kind == "RSS_EXCHANGE":
        return feeds.nse_feed(source.handle, c)
    raise ProviderError(source.kind, "no adapter for this kind of source")


def _already_seen(db: Session, source: Source, external_ids: list[str]) -> set[str]:
    """Which of these has already been stored.

    ⚠ Matched on `(source, external_id)` — the source NAME — because that is exactly the
    unique constraint the table carries. Checking `source_id` instead would look right and
    still collide, since the filings ingested before the register existed have no `source_id`
    at all and would be re-inserted on top of themselves.
    """
    if not external_ids:
        return set()
    rows = db.execute(
        sa.select(SourceItem.external_id).where(
            SourceItem.source == source.name, SourceItem.external_id.in_(external_ids)
        )
    ).scalars()
    return set(rows)


def _one_per_document(items: list[feeds.Item]) -> list[feeds.Item]:
    """One entry per document, carrying the words of every announcement of it.

    ⚠ **The feed announces one document several times.** Measured 21 Sep 2026: NSE's results
    feed returned four entries and two links — the same XBRL file announced twice, a second
    apart, once as `RELATING TO:Annual` and once as `RELATING TO:Fourth Quarter`. They are not
    duplicates; they are two readings of one filing.

    So the document is the unit — `source_items` is "one document the system has read", and
    its unique constraint agrees — but the bodies are **merged** rather than discarded,
    because the excerpt is the evidence and dropping one would throw away half of what the
    exchange said about the file.

    Without this, a poller would also collide with its own insert halfway through the batch,
    roll back, and lose the entire round rather than one entry.
    """
    order: list[str] = []
    bodies: dict[str, list[str]] = {}
    first: dict[str, feeds.Item] = {}
    for item in items:
        if item.external_id not in first:
            first[item.external_id] = item
            order.append(item.external_id)
            bodies[item.external_id] = []
        if item.body and item.body not in bodies[item.external_id]:
            bodies[item.external_id].append(item.body)

    out: list[feeds.Item] = []
    for key in order:
        item = first[key]
        merged = " | ".join(bodies[key])
        out.append(item if merged == item.body else replace(item, body=merged))
    return out


def poll(db: Session, source: Source, c: httpx.Client | None = None) -> PollResult:
    """Read one source, store what is new, and record every instrument it named.

    ⚠ Nothing is committed here. The caller owns the transaction, so a failure partway
    through a batch of sources leaves no half-read feed behind.
    """
    result = PollResult(source=source.name)
    if source.approved_at is None or not source.is_active:
        raise Unapproved(source.name)

    try:
        items = _fetch(source, c)
    except feeds.NotPublished:
        # ⚠ The feed said nothing. That is NOT the same as the source having published
        # nothing, and the difference is the whole reliability caveat on YouTube's RSS.
        source.last_polled_at = dt.datetime.now(dt.UTC)
        result.silent = True
        return result
    except ProviderError as exc:
        result.error = exc.reason
        return result

    result.fetched = len(items)
    items = _one_per_document(items)[:MAX_ITEMS_PER_POLL]
    seen = _already_seen(db, source, [item.external_id for item in items])
    fresh = [item for item in items if item.external_id not in seen]
    if not fresh:
        source.last_polled_at = dt.datetime.now(dt.UTC)
        return result

    vocab = vocabulary(db)
    now = dt.datetime.now(dt.UTC)
    # ⚠ The framework, if there is an approved one. A theme reading against an unapproved
    # framework would route attention using bottlenecks nobody has agreed to yet.
    try:
        spec = frameworks.current(db).spec
    except NotFound:
        spec = None

    # Whether this source is making a claim about a company or filing its own paperwork.
    claims = source.kind in CLAIMING_KINDS

    for item in fresh:
        text = f"{item.title}\n{item.body}".strip()
        found = named_in(text, vocab)
        # ⚠ An exchange feed is read for news about what you already follow. It names a couple
        # of hundred other companies a day as a matter of routine, and none of that is a lead.
        if not claims:
            found = [(target, excerpt) for target, excerpt in found if target.is_known]

        # ⚠ Every judgement about this item is formed BEFORE a single row is written, because
        # `mentions` refuses to be corrected afterwards.
        if found and source.trust_tier >= STANCE_READ_FROM_TIER:
            stances = stances_for(text, [target.symbol for target, _ in found])
        else:
            stances = {target.symbol: "MENTION_ONLY" for target, _ in found}

        # ⚠ Read BEFORE the row is written. `source_items` is append-only, and a first
        # version set this afterwards — the guard refused the update, which is it working on
        # its author again. A theme is part of what was read, not something discovered about
        # it later, so it belongs in the row from the start.
        item_themes = themes.read_themes(item.title, item.body, spec)

        row = SourceItem(
            id=uuid.uuid4(),
            kind=source.kind,
            instrument_id=(
                found[0][0].instrument_id if len(found) == 1 and found[0][0].is_known else None
            ),
            source_id=source.id,
            source=source.name,
            external_id=item.external_id,
            url=item.url,
            title=item.title[:500],
            published_at=item.published_at,
            fetched_at=now,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            excerpt=text[:2000],
            extraction={
                "feed": item.feed,
                "named": [t.symbol for t, _ in found],
                # ⚠ Recorded on every item, including ones that named a company. An article
                # can be about a theme AND a company, and treating the two as alternatives
                # would lose the sector read on exactly the pieces most worth having it for.
                "themes": item_themes,
            },
        )
        db.add(row)
        db.flush()
        result.stored += 1

        for theme in item_themes:
            if theme not in result.themes:
                result.themes.append(theme)

        for target, excerpt in found:
            mention = Mention(
                id=uuid.uuid4(),
                source_item_id=row.id,
                instrument_id=target.instrument_id,
                listed_company_id=target.listed_company_id,
                stance=stances.get(target.symbol, "MENTION_ONLY"),
                claim_excerpt=excerpt,
            )
            db.add(mention)
            db.flush()
            result.mentions += 1
            result.names.append(target.symbol)

            # ⚠ A company nobody follows opens a line in the research queue rather than being
            # dropped. This is the whole difference between a system that can say "look at
            # this" and one that can only ever say hold, trim or sell.
            if not target.is_known and note_candidate(db, target, mention, source, when=now):
                result.discovered.append(target.symbol)

    source.last_polled_at = now
    db.flush()
    return result


def poll_all(db: Session) -> list[PollResult]:
    """Every readable source, each isolated from the others' failures."""
    out: list[PollResult] = []
    c = http.client()
    try:
        for source in registered(db, only_readable=True, only_pollable=True):
            try:
                out.append(poll(db, source, c))
            except Unapproved:
                continue
            except Exception as exc:  # noqa: BLE001 - one bad feed must not end the round
                log.warning("poll of %s failed: %s", source.name, type(exc).__name__)
                out.append(PollResult(source=source.name, error=type(exc).__name__))
    finally:
        c.close()
    return out


# --- what a source is worth ------------------------------------------------------------------


@dataclass(frozen=True)
class Attribution:
    """What one source named, and how those names did.

    ⚠ `named` counts **everything**, including the companies that were never looked at. That
    denominator is why `mentions` exists at all: score a source on the ideas that were acted
    on and the number measures the reader's filter rather than the source.
    """

    source: str
    trust_tier: int
    named: int
    directional: int
    scored: int
    pending: int
    became_proposals: int
    hit_rate: watching.Measure


def _horizon_prices(
    db: Session, mentions: list[tuple[Mention, dt.date]]
) -> dict[uuid.UUID, tuple[list[dt.date], list[Decimal]]]:
    return history.price_series(db, sorted({m.instrument_id for m, _ in mentions}, key=str))


def attribution(
    db: Session, source: Source, *, horizon_days: int = 90, today: dt.date | None = None
) -> Attribution:
    """Did this source's directional calls work out, over a quarter?

    A BULL call is a hit if the price rose; a BEAR call is a hit if it fell. NEUTRAL and
    MENTION_ONLY make no claim and are counted but never scored — a source that names a
    company without taking a side cannot be right or wrong about it.

    ⚠ Gated at `MIN_OBSERVATIONS`, like every other measure in this module. A hit rate over
    six calls reads exactly like a hit rate over six hundred, and the reader cannot tell them
    apart unless the code refuses to show the first one.
    """
    today = today or dt.date.today()
    rows = list(
        db.execute(
            sa.select(Mention, SourceItem.published_at, SourceItem.fetched_at)
            .join(SourceItem, Mention.source_item_id == SourceItem.id)
            .where(SourceItem.source_id == source.id)
        ).all()
    )

    dated = [(m, (published or fetched).date()) for m, published, fetched in rows]
    directional = [(m, day) for m, day in dated if m.stance in ("BULL", "BEAR")]
    became = sum(1 for m, _ in dated if m.became_proposal_id is not None)

    series = _horizon_prices(db, directional) if directional else {}
    hits = scored = pending = 0
    for mention, day in directional:
        due = day + dt.timedelta(days=horizon_days)
        if due > today:
            pending += 1
            continue
        line = series.get(mention.instrument_id)
        then = history.value_as_of(line, day)
        later = history.value_as_of(line, due)
        # ⚠ `value_as_of` carries the last price forward, so a series that ends before the
        # horizon would answer with a stale price and score the call against a date that
        # never arrived. Checking the series' own end is what makes the read honest.
        covered = bool(line and line[0][-1] >= due)
        if then is None or later is None or not covered or then == 0:
            pending += 1
            continue
        scored += 1
        rose = later > then
        if (mention.stance == "BULL" and rose) or (mention.stance == "BEAR" and not rose):
            hits += 1

    if scored < watching.MIN_OBSERVATIONS:
        measure = watching.Measure(
            "source_hit_rate",
            None,
            scored,
            f"{scored} of {watching.MIN_OBSERVATIONS} settled calls needed before this "
            f"says anything about {source.name}",
        )
    else:
        measure = watching.Measure(
            "source_hit_rate",
            (Decimal(hits) / Decimal(scored)).quantize(Decimal("0.001")),
            scored,
            f"{hits} of {scored} directional calls went the way they were argued, "
            f"over {horizon_days} days",
        )

    return Attribution(
        source=source.name,
        trust_tier=source.trust_tier,
        named=len(dated),
        directional=len(directional),
        scored=scored,
        pending=pending,
        became_proposals=became,
        hit_rate=measure,
    )


def attributions(db: Session, *, today: dt.date | None = None) -> list[Attribution]:
    return [attribution(db, source, today=today) for source in registered(db)]


@dataclass(frozen=True)
class Heard:
    """One thing a source said about one instrument, for the reading list."""

    symbol: str
    name: str
    stance: str
    excerpt: str | None
    source: str
    trust_tier: int
    url: str | None
    published_at: dt.datetime | None
    is_held: bool


def recent(db: Session, *, days: int = 30, limit: int = 60) -> list[Heard]:
    """What has been said lately, newest first.

    ⚠ Whether it is held is shown but not filtered on. A reading list that hid the companies
    already owned would hide every piece of bad news about them, which is the half that
    actually costs money.
    """
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    rows = db.execute(
        sa.select(Mention, SourceItem, Instrument, Source)
        .join(SourceItem, Mention.source_item_id == SourceItem.id)
        .join(Instrument, Mention.instrument_id == Instrument.id)
        .join(Source, SourceItem.source_id == Source.id, isouter=True)
        .where(Mention.created_at >= since)
        .order_by(sa.func.coalesce(SourceItem.published_at, SourceItem.fetched_at).desc())
        .limit(limit)
    ).all()

    # ⚠ Through `portfolio.live`, never a hand-rolled filter. The ledger is append-only and a
    # correction is a NEW row pointing at the one it replaces, so "is this still held" has
    # exactly one definition and every query routes through it.
    held = set(
        db.execute(
            pf.live(
                sa.select(Transaction.instrument_id).join(
                    Portfolio, Transaction.portfolio_id == Portfolio.id
                )
            )
            .where(Portfolio.kind == "REAL")
            .distinct()
        ).scalars()
    )

    return [
        Heard(
            symbol=instrument.symbol,
            name=instrument.name,
            stance=mention.stance,
            excerpt=mention.claim_excerpt,
            source=source.name if source else item.source,
            trust_tier=source.trust_tier if source else FILING,
            url=item.url,
            published_at=item.published_at or item.fetched_at,
            is_held=instrument.id in held,
        )
        for mention, item, instrument, source in rows
    ]
