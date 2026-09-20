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
from app.db.models import Instrument, Mention, Portfolio, Source, SourceItem, Transaction
from app.services.investments import history, watching
from app.services.investments import portfolio as pf
from app.services.marketdata import feeds, http
from app.services.marketdata.http import ProviderError

log = logging.getLogger(__name__)

#: Tier 1 is a filing or a regulator; tier 2 the press; tier 3 commentary.
FILING, PRESS, COMMENTARY = 1, 2, 3

#: A stance is only ever asked of commentary. An exchange announcement has no direction — it
#: reports that something happened, and reading a bull case into "board meeting intimation"
#: would put noise straight into the attribution numbers.
STANCE_READ_FROM_TIER = PRESS

#: Below this many characters a symbol is too short to match safely. "ON", "IT" and "GO" are
#: all real tickers somewhere and all appear constantly in ordinary prose.
MIN_SYMBOL_LEN = 3

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
    """One instrument, and the shapes its name takes in text."""

    instrument_id: uuid.UUID
    symbol: str
    name: str
    patterns: tuple[re.Pattern, ...]

    def find(self, text: str) -> str | None:
        """The sentence that named it, or `None`. ⚠ The excerpt is the evidence: without it
        an attribution number cannot be checked back against what was actually said."""
        for pattern in self.patterns:
            match = pattern.search(text)
            if match:
                return _sentence_around(text, match.start())
        return None


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


def registered(db: Session, *, only_readable: bool = False) -> list[Source]:
    q = sa.select(Source).where(Source.deleted_at.is_(None))
    if only_readable:
        q = q.where(Source.is_active.is_(True), Source.approved_at.is_not(None))
    return list(db.execute(q.order_by(Source.trust_tier, Source.name)).scalars())


# --- who was named -------------------------------------------------------------------------


def _name_key(name: str) -> list[str]:
    """A company name reduced to the words that identify it, in order.

    Strips the trailing legal form and nothing else, so *Apar Industries Limited* keeps both
    words that make it Apar Industries and not some other Apar.
    """
    core = _TRAILING_FORM.sub("", (name or "").strip())
    return [word for word in re.split(r"[^A-Za-z0-9]+", core.lower()) if word]


def _sentence_around(text: str, index: int) -> str:
    start = max(text.rfind(". ", 0, index), text.rfind("\n", 0, index)) + 1
    end = text.find(". ", index)
    end = len(text) if end == -1 else end + 1
    return text[start:end].strip()[:EXCERPT_CHARS]


def catalogue(db: Session) -> list[Target]:
    """Every tracked instrument, with the patterns that would name it in text.

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

    out: list[Target] = []
    for row in rows:
        patterns: list[re.Pattern] = []
        symbol = (row.symbol or "").strip()
        if len(symbol) >= MIN_SYMBOL_LEN:
            # ⚠ Case-SENSITIVE on the symbol. Lower-cased, "apar" and "rolex" are ordinary
            # words; as tickers they are shouted, and requiring the shout removes most of
            # the false positives a symbol match would otherwise produce.
            patterns.append(re.compile(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])"))

        for candidate in [row.name, *(row.aliases or [])]:
            words = _name_key(candidate)
            if sum(len(word) for word in words) >= MIN_NAME_LEN:
                loose = _JOIN.join(re.escape(word) for word in words)
                patterns.append(
                    re.compile(rf"(?<![A-Za-z0-9]){loose}(?![A-Za-z0-9])", re.IGNORECASE)
                )

        if patterns:
            out.append(
                Target(
                    instrument_id=row.id,
                    symbol=symbol,
                    name=row.name,
                    patterns=tuple(patterns),
                )
            )
    return out


def named_in(text: str, targets: list[Target]) -> list[tuple[Target, str]]:
    """Every target the text names, with the sentence that named it."""
    found: list[tuple[Target, str]] = []
    for target in targets:
        excerpt = target.find(text)
        if excerpt:
            found.append((target, excerpt))
    return found


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

    targets = catalogue(db)
    now = dt.datetime.now(dt.UTC)

    for item in fresh:
        text = f"{item.title}\n{item.body}".strip()
        found = named_in(text, targets)

        # ⚠ Every judgement about this item is formed BEFORE a single row is written, because
        # `mentions` refuses to be corrected afterwards.
        if found and source.trust_tier >= STANCE_READ_FROM_TIER:
            stances = stances_for(text, [target.symbol for target, _ in found])
        else:
            stances = {target.symbol: "MENTION_ONLY" for target, _ in found}

        row = SourceItem(
            id=uuid.uuid4(),
            kind=source.kind,
            instrument_id=found[0][0].instrument_id if len(found) == 1 else None,
            source_id=source.id,
            source=source.name,
            external_id=item.external_id,
            url=item.url,
            title=item.title[:500],
            published_at=item.published_at,
            fetched_at=now,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            excerpt=text[:2000],
            extraction={"feed": item.feed, "named": [t.symbol for t, _ in found]},
        )
        db.add(row)
        db.flush()
        result.stored += 1

        for target, excerpt in found:
            db.add(
                Mention(
                    id=uuid.uuid4(),
                    source_item_id=row.id,
                    instrument_id=target.instrument_id,
                    stance=stances.get(target.symbol, "MENTION_ONLY"),
                    claim_excerpt=excerpt,
                )
            )
            result.mentions += 1
            result.names.append(target.symbol)

    source.last_polled_at = now
    db.flush()
    return result


def poll_all(db: Session) -> list[PollResult]:
    """Every readable source, each isolated from the others' failures."""
    out: list[PollResult] = []
    c = http.client()
    try:
        for source in registered(db, only_readable=True):
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
