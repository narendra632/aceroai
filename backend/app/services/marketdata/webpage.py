"""Reading a page someone dropped in.

⚠ **This is not a browser and does not pretend to be one.** It fetches a URL and reduces it to
the words on it — title, description, visible text — because the only thing downstream cares
about is *which companies are named and in what sentence*. A page that needs JavaScript to say
anything will come back nearly empty, and that is reported rather than hidden.

⚠ **No HTML parser, deliberately.** The project has none, and adding a dependency is a
decision to be asked about rather than slipped in. Tag-stripping is crude and entirely
sufficient here: the matcher works on words, and no layout survives into a mention anyway.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "WEB"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

#: How much of a page is kept. ⚠ Enough to find every company named in a normal article, far
#: less than the page — the module has a hard disk budget and stores no documents.
MAX_TEXT = 20_000

#: Hosts whose word is a filing rather than a report of one. ⚠ A drop from here is tier 1,
#: which is the difference between evidence a proposal may rest on and a lead that needs
#: corroboration. Matched on the registrable suffix, so a lookalike subdomain elsewhere does
#: not inherit the trust.
OFFICIAL_HOSTS = (
    "nseindia.com",
    "nsearchives.nseindia.com",
    "bseindia.com",
    "sebi.gov.in",
    "rbi.org.in",
    "sec.gov",
    "mca.gov.in",
    "pib.gov.in",
)

_SCRIPTS = re.compile(r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+'
    r'content=["\'](.*?)["\']',
    re.I | re.S,
)


@dataclass(frozen=True)
class Page:
    """What a dropped link turned out to say."""

    url: str
    title: str
    text: str
    #: ⚠ True when the page yielded almost nothing. Usually a JavaScript-only site or a login
    #: wall — and saying so is the difference between "nobody was named" and "nothing was read".
    is_thin: bool

    @property
    def is_official(self) -> bool:
        host = (urlparse(self.url).hostname or "").lower()
        return any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS)


def video_id(url: str) -> str | None:
    """The YouTube video this link points at, if it points at one."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "youtu.be":
        return parsed.path.lstrip("/").split("/")[0] or None
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            return (parse_qs(parsed.query).get("v") or [None])[0]
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if parsed.path.startswith(prefix):
                return parsed.path[len(prefix) :].split("/")[0] or None
    return None


def _strip(raw: str) -> str:
    without = _TAGS.sub(" ", _SCRIPTS.sub(" ", raw))
    return re.sub(r"\s+", " ", html.unescape(without)).strip()


def fetch(url: str, c: httpx.Client | None = None) -> Page:
    """Read a page down to its words.

    ⚠ A PDF is refused rather than mangled. Stripping tags from a binary produces plausible
    nonsense, and plausible nonsense in a research note is worse than an honest refusal —
    the whole module rests on a figure being traceable to words someone actually wrote.
    """
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

    kind = r.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind == "application/pdf" or url.lower().endswith(".pdf"):
        raise ProviderError(PROVIDER, "that is a PDF, and there is no reader for one yet")

    body = r.text
    title = _strip(m.group(1)) if (m := _TITLE.search(body)) else ""
    described = _strip(m.group(1)) if (m := _META.search(body)) else ""
    text = f"{title}\n{described}\n{_strip(body)}"[:MAX_TEXT]

    return Page(
        url=str(r.url),
        title=title or url,
        text=text,
        # A real article carries hundreds of words. Far below that and nothing was read,
        # whatever the request said.
        is_thin=len(text.split()) < 40,
    )


def youtube(url: str, c: httpx.Client | None = None) -> Page:
    """A video's title and description, without a key.

    ⚠ The **transcript** is not read. That needs an API key or one of several unofficial
    endpoints that break regularly, and a description is enough to learn which companies a
    video is about — which is all a lead has to establish.
    """
    ident = video_id(url)
    if ident is None:
        raise ProviderError(PROVIDER, "that is not a video link")

    page = fetch(f"https://www.youtube.com/watch?v={ident}", c)
    return Page(
        url=f"https://www.youtube.com/watch?v={ident}",
        title=page.title.removesuffix(" - YouTube").strip() or ident,
        text=page.text,
        is_thin=page.is_thin,
    )
