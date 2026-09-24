"""What was actually said in a video, rather than what the title advertised.

A YouTube title and description tell you almost nothing. *"Midcap 150 & Nifty Next 50: Is
Valuation Comfort Finally Back?"* names no company at all; the thirty companies the presenter
then walks through are in the spoken words and nowhere else. Reading titles and treating the
result as a measurement of what commentators talk about was measuring the wrong thing — it
counted advertising copy and reported it as coverage.

⚠ **The captions are not reachable the obvious way any more.** The watch page still lists
caption tracks, and their `baseUrl`s still return HTTP 200 — with a body of zero bytes.
Measured, not assumed: a 200 with nothing in it is the failure mode that looks most like
success, and code that trusted the status line would have recorded every video as having no
transcript. The mobile clients' player endpoint still serves them, so that is what is used.

⚠ **This is an unsupported endpoint and will break.** It is the same class of source as the
uploads feed above it: no key, no quota, no promise. So a failure here is `None` and a note,
never an exception that fails the poll — a video whose captions could not be read must not
look like a video that said nothing, for exactly the reason the mention register exists.

⚠ **The language is recorded, because most Indian finance commentary is not in English.**
Measured on Yadnya's channel: both recent uploads carry auto-generated **Hindi** captions in
Devanagari, and the name matcher is deterministic over Latin-script names. Those transcripts
are stored and counted as read, and flagged as unmatched-by-script — so the diagnostic says
"read, in Hindi, not name-matchable" instead of the flatly false "named no companies". The
survivorship rule, again: an unreadable source must never be indistinguishable from an empty
one. YouTube's own translation parameter was tried and answers 429.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

log = logging.getLogger(__name__)

PROVIDER = "YOUTUBE_CAPTIONS"

#: ⚠ **No API key, deliberately.** Every published recipe for this endpoint appends the public
#: InnerTube key that YouTube embeds in its own pages. It is not a credential — it is the same
#: constant for every visitor on earth and authorises nothing — but a forty-character string
#: beginning `AIza` is indistinguishable from a real Google key to any reader and to the
#: secret scanner, which refused this commit and was right to. Measured 24 Sep 2026: the
#: endpoint answers `status=OK` with the caption tracks and no key at all. So the safest
#: version of this line is the one that is not here.
PLAYER_URL = "https://www.youtube.com/youtubei/v1/player"

#: The clients whose player response still carries working caption URLs, in the order tried.
#: Measured 24 Sep 2026: WEB and MWEB answer `UNPLAYABLE` with no tracks, TVHTML5 errors, and
#: these two return the tracks and serve them.
CLIENTS = (
    {"clientName": "IOS", "clientVersion": "20.10.4"},
    {"clientName": "ANDROID", "clientVersion": "20.10.38", "androidSdkVersion": 30},
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal portfolio; research feed reader)",
    "Content-Type": "application/json",
}

#: How much spoken text is kept. A three-hour livestream would otherwise arrive whole, and
#: nothing downstream is better for the last two hours of it. ⚠ Only matching happens on this
#: text; what is *stored* is far smaller still.
MAX_CHARS = 60_000

#: Below this share of Latin letters the text is another script, and the deterministic name
#: matcher — which knows 2,595 names written in Latin — cannot see anything in it.
LATIN_SHARE = 0.5


@dataclass(frozen=True)
class Transcript:
    """What was said, and enough about it to know what the reading is worth."""

    text: str
    #: "en", "hi", … as YouTube labels the track.
    language: str
    #: True where nobody wrote these captions — a machine heard them. Names come out
    #: mangled ("Kaynes" as "canes"), so a miss on an auto track means less than a miss on
    #: a written one.
    is_auto: bool
    #: False where the text is in a script the name matcher cannot read.
    is_matchable: bool
    words: int

    def note(self) -> str:
        kind = "auto-generated" if self.is_auto else "published"
        if self.is_matchable:
            return f"{self.words} words of {kind} {self.language} captions"
        return (
            f"{self.words} words of {kind} {self.language} captions — not in Latin script, so "
            "no company name could be matched in it either way"
        )


def _latin_share(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if "a" <= ch.lower() <= "z") / len(letters)


def _pick(tracks: list[dict]) -> dict | None:
    """Which caption track to read.

    ⚠ A written track beats an auto one and English beats everything, because both decide how
    much a *miss* means. Auto-generated Hindi missing "Kaynes" is close to no evidence; a
    published English transcript missing it is real evidence the video did not mention it, and
    the attribution measure divides by exactly that distinction.
    """
    if not tracks:
        return None

    def rank(track: dict) -> tuple[int, int]:
        is_auto = track.get("kind") == "asr"
        is_english = (track.get("languageCode") or "").startswith("en")
        return (0 if not is_auto else 1, 0 if is_english else 1)

    return sorted(tracks, key=rank)[0]


def _player(video_id: str, client: dict, c: httpx.Client) -> dict:
    def attempt() -> httpx.Response:
        r = c.post(
            PLAYER_URL,
            json={"context": {"client": client}, "videoId": video_id},
            headers=_HEADERS,
        )
        r.raise_for_status()
        return r

    return http.with_retries(PROVIDER, attempt).json()


def _words(payload: str) -> str:
    """Flatten the timed caption events into running prose.

    ⚠ Joined with spaces and stripped of the newlines YouTube breaks lines on. A caption file
    wraps mid-sentence, so "Kaynes\\nTechnology" is one company written across two lines — and
    a matcher looking for the name would see two words that are not it.
    """
    events = json.loads(payload).get("events", [])
    pieces = [seg.get("utf8", "") for event in events for seg in (event.get("segs") or []) if seg]
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


def fetch(video_id: str, c: httpx.Client | None = None) -> Transcript | None:
    """What was said in this video, or `None` when it cannot be read.

    ⚠ **`None` is not "the video said nothing".** It means the captions were unreachable —
    no track published, the endpoint changed, a 429. The caller records that distinction;
    collapsing the two is the survivorship error this whole subsystem is built against.
    """
    own = c is None
    c = c or http.client()
    try:
        for client in CLIENTS:
            try:
                data = _player(video_id, client, c)
            except ProviderError as exc:
                log.info("captions: player refused for %s (%s)", video_id, exc.reason)
                continue

            tracks = (
                data.get("captions", {})
                .get("playerCaptionsTracklistRenderer", {})
                .get("captionTracks", [])
            )
            track = _pick(tracks)
            if track is None:
                # A real answer, not a failure: this video has no captions at all. Trying the
                # next client would ask the same question a second time.
                return None

            r = c.get(track["baseUrl"] + "&fmt=json3", headers=_HEADERS)
            # ⚠ 200 with an empty body is the documented-by-measurement failure of the old
            # route, and the one a status check alone would have called success.
            if r.status_code != 200 or not r.text.strip().startswith("{"):
                log.info(
                    "captions: %s served %s bytes for %s",
                    client["clientName"],
                    len(r.text),
                    video_id,
                )
                continue

            text = _words(r.text)[:MAX_CHARS]
            if not text:
                continue
            return Transcript(
                text=text,
                language=track.get("languageCode") or "unknown",
                is_auto=track.get("kind") == "asr",
                is_matchable=_latin_share(text) >= LATIN_SHARE,
                words=len(text.split()),
            )
        return None
    except httpx.HTTPError as exc:
        log.info("captions: unreachable for %s (%s)", video_id, type(exc).__name__)
        return None
    finally:
        if own:
            c.close()
