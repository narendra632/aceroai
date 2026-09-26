"""Reading the world: exchange announcements, and what commentators are saying.

Two adapters, neither needing a key.

**NSE's own RSS feeds** are the best free source in this whole design. Announcements, results,
board meetings, shareholding, insider trading — the exchange's official firehose, no login, no
quota, and it is *tier 1*: what a company tells the exchange is a filing, not a report of one.

**YouTube channel RSS** gives new uploads without an API key or a quota. ⚠ It is an unsupported
endpoint and is reported to fail intermittently — occasional 404s, silent multi-day gaps, and a
window of only the last ~15 items. So a missed video is expected and must not be treated as
"nothing happened": the poller records what it saw and never infers absence.

⚠ **Nothing here judges materiality or extracts meaning.** These adapters fetch and parse. What
an item *means* is a separate step, and keeping them apart is what lets the record of "this was
published" survive independently of whatever the reading of it concluded.
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "NSE_RSS"
YOUTUBE_PROVIDER = "YOUTUBE_RSS"

#: The exchange's feeds. ⚠ `Corporate_action.xml` is read elsewhere, by the job that applies
#: splits — it is the one feed whose items change the ledger rather than informing a view.
NSE_FEEDS: dict[str, str] = {
    "announcements": "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
    "results": "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",
    "board_meetings": "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml",
    "shareholding": "https://nsearchives.nseindia.com/content/RSS/Shareholding_Pattern.xml",
    "insider": "https://nsearchives.nseindia.com/content/RSS/InsiderTrading.xml",
}

YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

_HEADERS = {"User-Agent": "Mozilla/5.0 (personal portfolio; research feed reader)"}

#: How much of an item's text is kept. ⚠ Enough to check a reading against, never the
#: document — the module's storage budget forbids documents and the excerpt column caps at 2 KB.
EXCERPT_CAP = 1500


class NotPublished(Exception):
    """The feed answered with nothing usable. Common for YouTube RSS; not a failure."""


@dataclass(frozen=True)
class Item:
    """One thing that was published, before anyone has decided what it means."""

    external_id: str
    title: str
    url: str | None
    published_at: dt.datetime | None
    body: str
    #: Which feed produced it, for the source register.
    feed: str


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _parse_when(raw: str) -> dt.datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%d-%b-%Y %H:%M:%S",
    ):
        try:
            when = dt.datetime.strptime(raw, fmt)
            return when if when.tzinfo else when.replace(tzinfo=dt.UTC)
        except ValueError:
            continue
    return None


def _clean(raw: str) -> str:
    """Strip tags and squeeze whitespace. Feed bodies arrive with markup in them."""
    without_tags = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", without_tags).strip()[:EXCERPT_CAP]


def nse_feed(name: str, c: httpx.Client | None = None) -> list[Item]:
    """Every current item in one of the exchange's feeds.

    ⚠ The feed is a WINDOW, not a history — it holds the last few hundred items and older ones
    simply vanish. So polling has to be frequent enough that nothing falls out between reads,
    and a gap can never be recovered by asking again later.
    """
    url = NSE_FEEDS.get(name)
    if url is None:
        raise ProviderError(PROVIDER, f"no feed called {name!r}")

    own = c is None
    c = c or http.client()

    def attempt() -> httpx.Response:
        r = c.get(url, headers=_HEADERS)
        r.raise_for_status()
        return r

    try:
        r = http.with_retries(PROVIDER, attempt)
    finally:
        if own:
            c.close()

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        raise ProviderError(PROVIDER, f"the {name} feed was not XML") from None

    # ⚠ NSE answers a blocked client with an HTML page, and an HTML page is *valid XML*. So
    # parsing alone proves nothing: without this check the adapter would return an empty list
    # and the poller would read it as "the exchange announced nothing today".
    if root.tag != "rss":
        raise ProviderError(PROVIDER, f"the {name} feed answered with a {root.tag} document")

    out: list[Item] = []
    for node in root.iter("item"):
        title = _text(node.find("title"))
        body = _clean(_text(node.find("description")))
        link = _text(node.find("link")) or None
        when = _parse_when(_text(node.find("pubDate")))
        if not title and not body:
            continue
        # ⚠ The feed carries no stable id, so one is derived from what identifies the item:
        # its link where there is one, else the title and time together. A guid that changed
        # between polls would re-ingest the same announcement every hour.
        external_id = link or f"{name}|{title}|{when.isoformat() if when else '?'}"
        out.append(
            Item(
                external_id=external_id,
                title=title,
                url=link,
                published_at=when,
                body=body,
                feed=name,
            )
        )
    return out


@dataclass(frozen=True)
class Channel:
    """A YouTube channel, resolved from whatever form a person pasted."""

    channel_id: str
    title: str
    url: str


#: Where a channel page names ITSELF, most authoritative first.
#:
#: ⚠ **The first `channelId` on a page is not the page's channel.** An earlier version took
#: whichever of `externalId` or `channelId` appeared first, on the belief that the two were
#: always the same value. Measured 27 Sep 2026: `@zerodhaonline` carries ten distinct
#: `channelId`s — featured channels, collaborations — and the first of them is a different
#: channel. The page's own id is `UC59YUBh…`; the resolver returned `UCjOVNkq…`. The title came
#: from the right channel and the uploads from the wrong one, so the reading list would have
#: shown one name while polling someone else — silently, and in the table that measures where
#: ideas come from. It is also the likeliest reason the originally seeded "Zerodha" came back
#: in Hindi.
#:
#: The canonical link and `externalId` both describe the page's owner. A bare `channelId` is
#: never used: a page that offers nothing better is not trusted to be a channel page at all.
_CHANNEL_SELF = (
    re.compile(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{20,})"'),
    re.compile(r'"externalId":"(UC[\w-]{20,})"'),
)
_CHANNEL_TITLE = re.compile(r'<meta property="og:title" content="([^"]+)"')


def resolve_channel(pasted: str, c: httpx.Client | None = None) -> Channel:
    """Turn whatever a person pasted into the channel id the uploads feed needs.

    ⚠ **The uploads feed takes a `UC…` id and nothing else**, and nobody has one to hand. What
    people have is the address bar: `youtube.com/@zerodhaonline`, an old `/c/` vanity path, a
    video they liked. Requiring the id would make adding a channel a research task, and a
    channel list that is hard to change is a channel list that never gets changed — which is
    the whole reason the current three are measurably the wrong three.

    Verified 24 Sep 2026 against `@handle`, a full `@` URL, a bare `UC…` id and a legacy `/c/`
    path: all four resolve. Re-verified 27 Sep 2026 after the id was found to be taken from the
    wrong channel on pages that feature others — see `_CHANNEL_SELF`.
    """
    raw = (pasted or "").strip()
    if not raw:
        raise ProviderError(YOUTUBE_PROVIDER, "nothing was pasted")

    if raw.startswith("http://") or raw.startswith("https://"):
        url = raw
    elif raw.startswith("@"):
        url = f"https://www.youtube.com/{raw}"
    elif re.fullmatch(r"UC[\w-]{20,}", raw):
        url = f"https://www.youtube.com/channel/{raw}"
    else:
        url = f"https://www.youtube.com/@{raw}"

    own = c is None
    c = c or http.client()

    def attempt() -> httpx.Response:
        r = c.get(url, headers=_HEADERS)
        r.raise_for_status()
        return r

    try:
        r = http.with_retries(YOUTUBE_PROVIDER, attempt)
    finally:
        if own:
            c.close()

    found = next((m for pattern in _CHANNEL_SELF if (m := pattern.search(r.text))), None)
    if not found:
        # ⚠ A video URL, a playlist, a search page or a typo all land here. Named as what it
        # is rather than as a network failure, because the two need different fixes.
        raise ProviderError(YOUTUBE_PROVIDER, "that page is not a channel")

    title = _CHANNEL_TITLE.search(r.text)
    channel_id = found.group(1)
    return Channel(
        channel_id=channel_id,
        title=_clean(title.group(1)) if title else channel_id,
        url=f"https://www.youtube.com/channel/{channel_id}",
    )


def youtube_uploads(channel_id: str, c: httpx.Client | None = None) -> list[Item]:
    """A channel's recent uploads, without a key or a quota.

    ⚠ This endpoint is unsupported and unreliable: intermittent 404s, silent multi-day gaps,
    and a window of roughly the last fifteen videos. A poll returning nothing means **the feed
    said nothing**, not that the channel published nothing — and the difference matters,
    because source attribution counts what a source named and would be wrong if a missed video
    silently became "said nothing".
    """
    own = c is None
    c = c or http.client()

    def attempt() -> httpx.Response:
        r = c.get(YOUTUBE_FEED.format(channel_id=channel_id), headers=_HEADERS)
        if r.status_code in (403, 404):
            return r
        r.raise_for_status()
        return r

    try:
        r = http.with_retries(YOUTUBE_PROVIDER, attempt)
    finally:
        if own:
            c.close()

    if r.status_code in (403, 404):
        raise NotPublished(channel_id)

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        raise NotPublished(channel_id) from None

    out: list[Item] = []
    for node in root.iter():
        if not node.tag.endswith("}entry") and node.tag != "entry":
            continue
        values = {child.tag.split("}")[-1]: child for child in node}
        video_id = _text(values.get("videoId"))
        title = _text(values.get("title"))
        if not video_id or not title:
            continue
        description = ""
        for child in node.iter():
            if child.tag.split("}")[-1] == "description":
                description = _clean(_text(child))
                break
        out.append(
            Item(
                external_id=f"yt:{video_id}",
                title=title,
                url=f"https://www.youtube.com/watch?v={video_id}",
                published_at=_parse_when(_text(values.get("published"))),
                body=description,
                feed="youtube",
            )
        )
    if not out:
        raise NotPublished(channel_id)
    return out
