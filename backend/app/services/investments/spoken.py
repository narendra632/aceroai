"""Reading company names out of commentary that is not written in Latin script.

Measured 24 Sep 2026 against the three registered channels: Yadnya and Zerodha both publish
auto-generated **Hindi** captions in Devanagari — 819 to 10,535 words per video — and the name
matcher is deterministic over 2,595 names written in Latin. So the transcripts arrived, were
stored, and matched nothing. A source in Hindi and a source that named no company are not the
same finding, and without this they were the same row.

⚠ **The model transliterates; it never introduces a company.** This is the same boundary
`deduce` sits on, arranged differently. There the model picks from a closed list of 31 ids;
here it hands back Latin-script *strings*, and the exchange's own listed register decides
whether any of them is a company. A hallucinated "Reliance Powers Limited" is matched against
2,595 real names and found in none of them, exactly as a misheard one would be. **The
vocabulary is still the exchange's, and a model cannot add to it.**

⚠ **Every name must arrive with the words it was heard in, and those words must really be
there.** The model returns a verbatim snippet alongside each name, and a snippet that is not
present in the transcript takes its name down with it. This is `judgement._echoes` applied to
a different kind of claim: it is the cheapest available check that the model read the
document rather than its own expectations, and on a transcript it is the only one.

⚠ **Only non-Latin transcripts reach here.** An English video is matched deterministically and
costs nothing, which keeps the model off the path that produces most of the evidence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from app.services.investments import billing

log = logging.getLogger(__name__)

#: ⚠ Low effort. Reading names out of a transcript is transcription, not argument, and the
#: check that follows is deterministic — a better model would produce a nicer list of
#: candidates for the exchange's register to reject at exactly the same rate.
EFFORT = "low"

#: How much of a transcript is sent. A three-hour livestream is 60,000 characters and the
#: names in its last hour are not worth the prompt. ⚠ Truncation is silent to the model and
#: counted here, so a short read is never mistaken for a quiet video.
MAX_CHARS = 30_000

#: Most a single video may contribute. A model asked for "every company mentioned" in a market
#: round-up will happily list eighty, and eighty names from one video would swamp the mention
#: register the attribution measure divides by.
MAX_NAMES = 25

#: A snippet shorter than this proves nothing — two characters appear in any document.
MIN_SNIPPET = 8

_PROMPT = """You are reading a transcript of an Indian stock-market video. The transcript is
auto-generated speech, in Hindi or another Indic script, and may be misheard in places.

List the LISTED INDIAN COMPANIES that are actually discussed.

Rules:
- Write each company's name in ENGLISH / Latin script, as it appears on the stock exchange.
  "एचडीएफसी बैंक" becomes "HDFC Bank". "टाटा मोटर्स" becomes "Tata Motors".
- Only companies the speaker actually talks about. NOT indices (Nifty, Sensex, Bank Nifty),
  NOT mutual funds, NOT sectors, NOT the broker or channel whose video this is.
- For each one, quote `said`: a short run of the ORIGINAL transcript, copied exactly,
  character for character, where that company is named. Do not translate it, do not tidy it,
  do not write it in Latin. A quote that is not in the transcript discards the name with it.
- If no listed company is discussed, answer {"companies": []}. That is a common and correct
  answer: most market commentary is about indices and themes.

Reply with JSON only:
{"companies": [{"name": "HDFC Bank", "said": "<verbatim from the transcript>"}]}"""


@dataclass(frozen=True)
class Named:
    """A company name the model read, and the words it says it read them in."""

    name: str
    said: str


def _normalise(text: str) -> str:
    """Collapse whitespace, so a quote that differs only in spacing still echoes."""
    return re.sub(r"\s+", " ", text or "").strip()


async def _ask(text: str) -> dict:
    reply = await billing.complete(
        [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": f"Transcript:\n{text}"},
        ],
        effort=EFFORT,
        purpose="transliterate",
    )
    body = reply[reply.find("{") : reply.rfind("}") + 1]
    return json.loads(body)


def _run(text: str) -> dict:
    # Sync callers (the polling job, the API) have no event loop of their own, so `asyncio.run`
    # is correct here rather than a borrowed loop — the same pattern `deduce` and the stance
    # read already use.
    return asyncio.run(_ask(text))


def names_in(text: str) -> list[Named]:
    """Candidate company names heard in a transcript, each with the words it was heard in.

    ⚠ These are **candidates and nothing more.** Nothing here has been checked against the
    exchange's register; that is the caller's job and it is what makes this safe. Returning an
    empty list on any failure is deliberate — a provider outage must read as "no names were
    read", never as "the video named nobody", and the caller records which.
    """
    body = _normalise(text)[:MAX_CHARS]
    if not body:
        return []

    try:
        answer = _run(body)
    except Exception as exc:  # noqa: BLE001 — provider, parse or shape failure all land here
        log.info("spoken name reading failed (%s); no names taken", type(exc).__name__)
        return []

    out: list[Named] = []
    seen: set[str] = set()
    for row in answer.get("companies", [])[:MAX_NAMES]:
        if not isinstance(row, dict):
            continue
        name = _normalise(str(row.get("name", "")))[:120]
        said = _normalise(str(row.get("said", "")))[:400]
        if not name or len(said) < MIN_SNIPPET:
            continue
        # ⚠ The echo gate. The quote has to be in the document the model was given, or the
        # name it carries goes with it. A model that answers from what it expects an Indian
        # market video to contain writes fluent, plausible quotes that are not there.
        if said not in body:
            log.info("spoken: dropped %r — its quote is not in the transcript", name)
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(Named(name=name, said=said))
    return out
