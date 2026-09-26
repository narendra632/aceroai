"""The six flags a model is allowed to answer, and the four gates it has to get past.

Ten red flags. Four are arithmetic and live in `scoring` — a measurable thing must never be a
matter of opinion, and those four are the ones a persuasive narrative would most easily argue
away. The other six are genuinely qualitative: whether a business is outside a circle of
competence, whether management is candid, whether a narrative has run ahead of execution.

⚠ **Every flag is a RED flag. YES is bad.**

⚠ **A verdict without a citation is not a verdict.** Each answer must quote the words it rests
on, and four separate things have to be true before that answer is kept:

1. **It cited something.** No excerpt → `UNKNOWN`. Not "probably yes" — unknown.
2. **The words are really there.** The quote is checked back against the evidence that was
   handed over, character for character after whitespace is normalised. A model that could
   invent its own evidence would make the citation requirement decorative.
3. **A second model agrees the quote supports the verdict.** It sees only the question, the
   answer and the quote — never the company, never the other flags — so it cannot be carried
   along by the story. Disagreement → `UNKNOWN`, and the disagreement is recorded.
4. **It stayed out of arithmetic.** A verdict that smuggles in a figure is refused, because
   every number in this module comes from a filing and none comes from a model.

⚠ **The computed flags always win.** Where a flag can be measured, the measurement overwrites
whatever was judged, and this module never returns one of them.

⚠ **`PARTIAL` is a real answer**, against the spec's three-value vocabulary and in favour of
how the framework is actually used: the June analysis marks flags PARTIAL throughout and says
*"PARTIAL flags excluded from count"*. It is kept as its own verdict and counted like NO, so
the count matches the notes while the distinction between "no" and "somewhat" survives.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Fundamental, Mention, SourceItem
from app.services.investments import billing
from app.services.investments.scoring import Flag

log = logging.getLogger(__name__)

#: ⚠ Verbatim from the framework. Reworded questions produce answers to a different question,
#: and nothing downstream would notice.
JUDGED: dict[int, str] = {
    1: (
        "Is the business model heavily complex, highly vulnerable to rapid technological "
        "obsolescence, or outside a standard circle of competence?"
    ),
    3: (
        "Does the company require massive, continuous capital expenditures just to maintain "
        "its current competitive position (weak Owner Earnings)?"
    ),
    4: (
        "Is management destroying value through expensive, dilutive acquisitions or buying "
        "back shares at historically overvalued multiples?"
    ),
    5: (
        "Is there a lack of candor in management communications (e.g., hiding poor "
        "performance behind adjusted EBITDA or changing key metrics)?"
    ),
    7: (
        "Is the business model heavily dependent on the continuation of a high stock price or "
        "cheap capital access to fuel its growth or survival?"
    ),
    9: (
        "Is there a highly concentrated, hype-driven narrative dominating social media and "
        "institutional research that ignores execution risks?"
    ),
}

#: ⚠ Never judged. These are measured in `scoring`, and a model verdict on them is discarded
#: before it can reach anything.
COMPUTED = (2, 6, 8, 10)

VERDICTS = ("YES", "NO", "PARTIAL", "UNKNOWN")

#: Counted as a YES. ⚠ PARTIAL is not, matching the framework's own note that partial flags are
#: excluded from the count.
COUNTS_AS_RED = ("YES",)

#: How much evidence one company's judgement is given. ⚠ Capped because the whole point is that
#: the answer rests on specific words that can be checked; a wall of text makes the citation
#: requirement unfalsifiable in practice.
MAX_EXCERPTS = 12
EXCERPT_CHARS = 700

#: ⚠ Below this many characters a quote is not a citation. "growth" appears in every filing
#: ever written and would pass an echo check against any of them.
MIN_QUOTE = 25

EFFORT = "low"


@dataclass(frozen=True)
class Judged:
    """One judged flag, and everything that had to be true for it to survive."""

    number: int
    question: str
    verdict: str
    quote: str | None
    reasoning: str
    #: ⚠ False when the second model disagreed that the quote supports the verdict. Recorded
    #: rather than hidden: a pattern of disagreement is a fact about the first model.
    verifier_agreed: bool | None = None
    #: Why it ended up UNKNOWN, when it did.
    withheld_because: str | None = None

    def as_flag(self) -> Flag:
        evidence = self.quote or self.withheld_because or "no evidence was cited"
        return Flag(
            number=self.number,
            question=self.question,
            verdict=self.verdict,
            evidence=evidence,
            computed=False,
        )


# --- what the model is allowed to see --------------------------------------------------------


def evidence_for(db: Session, instrument_id: uuid.UUID) -> list[str]:
    """The words this company's judgement may rest on.

    ⚠ Filings first, then commentary. Flag 9 is about narrative and no filing can evidence it,
    so commentary has to be present — but a filing is the better evidence for every other
    flag, and an ordering that buried them under videos would invite the weaker citation.
    """
    filings = db.execute(
        sa.select(SourceItem.excerpt)
        .where(SourceItem.instrument_id == instrument_id)
        .order_by(SourceItem.published_at.desc().nullslast())
        .limit(MAX_EXCERPTS)
    ).scalars()

    commentary = db.execute(
        sa.select(Mention.claim_excerpt)
        .where(Mention.instrument_id == instrument_id)
        .order_by(Mention.created_at.desc())
        .limit(MAX_EXCERPTS)
    ).scalars()

    seen: list[str] = []
    for raw in [*filings, *commentary]:
        cleaned = _flatten(raw or "")[:EXCERPT_CHARS]
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen[:MAX_EXCERPTS]


def figures_for(db: Session, instrument_id: uuid.UUID) -> list[str]:
    """Filed figures, as text, so a judgement about capex or dilution has numbers to point at.

    ⚠ Handed over as evidence to READ, never as numbers to restate. A verdict that quotes one
    of these lines is citing a filing; a verdict that computes with them is doing arithmetic
    the model is not allowed to do, which is what `_is_arithmetic` refuses.
    """
    rows = db.execute(
        sa.select(
            Fundamental.fiscal_period, Fundamental.metric_key, Fundamental.value, Fundamental.unit
        )
        .where(Fundamental.instrument_id == instrument_id)
        .order_by(Fundamental.fiscal_period.desc(), Fundamental.metric_key)
        .limit(60)
    ).all()
    return [f"{period} {metric}: {value} {unit}" for period, metric, value, unit in rows]


def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# --- asking ----------------------------------------------------------------------------------

_PROMPT = """You are answering a fixed checklist about one company. Every item is a RED flag,
so YES means something is wrong.

You will be given the checklist and a numbered list of EVIDENCE — excerpts from the company's
own filings and from commentary about it. Answer each item using only that evidence.

For each item give:
  verdict  YES | NO | PARTIAL | UNKNOWN
  quote    the exact words from the evidence that justify it, copied character for character
  why      one sentence

Rules that are enforced, not requested:
- A verdict with no quote becomes UNKNOWN. A verdict whose quote is not found in the evidence
  becomes UNKNOWN. Copy, do not paraphrase.
- UNKNOWN is the correct answer far more often than it feels. Most of these cannot be settled
  from a few excerpts, and an unsupported NO is as wrong as an unsupported YES.
- Do not calculate anything. Do not state a ratio, a percentage, a growth rate or any figure
  you worked out yourself. Quote figures only as they appear.

Reply with JSON only:
{"flags": [{"number": 1, "verdict": "UNKNOWN", "quote": "", "why": "..."}]}"""

_VERIFY_PROMPT = """Does this quote support this verdict? Answer yes or no, nothing else.

You are shown one checklist question, one verdict and one quote. You are deliberately not told
which company it is or what any other answer was, so you cannot be carried along by a story.

Say "no" if the quote is about something else, if it is too vague to support the verdict, or
if it would equally support the opposite verdict.

Reply with JSON only: {"supports": true}"""


async def _ask(question_block: str, evidence_block: str) -> dict:
    reply = await billing.complete(
        [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": f"{question_block}\n\nEVIDENCE:\n{evidence_block}"},
        ],
        effort=EFFORT,
        purpose="judge",
    )
    return json.loads(reply[reply.find("{") : reply.rfind("}") + 1])


async def _verify(question: str, verdict: str, quote: str) -> bool:
    reply = await billing.complete(
        [
            {"role": "system", "content": _VERIFY_PROMPT},
            {
                "role": "user",
                "content": f"Question: {question}\nVerdict: {verdict}\nQuote: {quote}",
            },
        ],
        effort=EFFORT,
        purpose="verify",
    )
    parsed = json.loads(reply[reply.find("{") : reply.rfind("}") + 1])
    return bool(parsed.get("supports"))


# --- the four gates --------------------------------------------------------------------------

#: A verdict that contains a figure the model worked out. ⚠ Quoting a filed number is fine;
#: producing a ratio, a percentage or a growth rate is arithmetic, and every number in this
#: module comes from a filing.
_ARITHMETIC = re.compile(
    r"\b\d+(\.\d+)?\s*(%|percent|x\b|times\b|bps\b)|\b(cagr|yoy|margin of|roe of|roce of)\b",
    re.IGNORECASE,
)


def _is_arithmetic(text: str) -> bool:
    return bool(_ARITHMETIC.search(text or ""))


def _echoes(quote: str, evidence: list[str]) -> bool:
    """Whether the quoted words are really in the evidence.

    ⚠ The check that makes the citation requirement mean something. Compared after whitespace
    is flattened, because a model reflowing a line is not the same as inventing one — but not
    after any other normalisation, because every further liberty taken here is a liberty taken
    with what counts as evidence.
    """
    needle = _flatten(quote)
    if len(needle) < MIN_QUOTE:
        return False
    return any(needle.lower() in _flatten(source).lower() for source in evidence)


def _settle(
    number: int,
    raw: dict,
    evidence: list[str],
    *,
    verify: bool = True,
) -> Judged:
    """Put one answer through all four gates."""
    question = JUDGED[number]
    verdict = str(raw.get("verdict", "")).strip().upper()
    quote = str(raw.get("quote", "") or "").strip()
    why = str(raw.get("why", "") or "").strip()[:400]

    def withheld(reason: str) -> Judged:
        return Judged(number, question, "UNKNOWN", None, why, None, reason)

    if verdict not in VERDICTS:
        return withheld(f"the answer was not one of {', '.join(VERDICTS)}")
    if verdict == "UNKNOWN":
        return Judged(number, question, "UNKNOWN", None, why, None, why or "answered unknown")

    if not quote:
        return withheld("no words were cited, and a verdict without a citation is an opinion")
    if not _echoes(quote, evidence):
        # ⚠ The most important refusal here. A model that could invent its own evidence would
        # make every other guard decorative.
        return withheld("the quoted words are not in the evidence that was provided")
    if _is_arithmetic(why) or _is_arithmetic(quote):
        return withheld("the answer calculated a figure, and every number here comes from a filing")

    if not verify:
        return Judged(number, question, verdict, quote, why, None)

    try:
        agreed = asyncio.run(_verify(question, verdict, quote))
    except Exception as exc:  # noqa: BLE001 - a verifier that cannot be reached must not pass
        log.warning("verifier unreachable (%s); withholding flag %s", type(exc).__name__, number)
        return withheld("the second reader could not be reached, so this was not confirmed")

    if not agreed:
        return Judged(
            number,
            question,
            "UNKNOWN",
            quote,
            why,
            verifier_agreed=False,
            withheld_because="a second reader did not agree the quote supports this",
        )
    return Judged(number, question, verdict, quote, why, verifier_agreed=True)


def judged_flags(
    db: Session,
    instrument,
    *,
    verify: bool = True,
) -> list[Judged]:
    """The six qualitative flags, each having survived citation, echo, verifier and arithmetic.

    ⚠ Nothing is asked at all when there is no evidence. A model given no excerpts will still
    answer, and its answers would be exactly the unsourced opinion this design exists to keep
    out of the record.
    """
    evidence = evidence_for(db, instrument.id) + figures_for(db, instrument.id)
    if not evidence:
        return [
            Judged(n, q, "UNKNOWN", None, "", None, "nothing has been read about this company yet")
            for n, q in JUDGED.items()
        ]

    numbered = "\n".join(f"[{i + 1}] {row}" for i, row in enumerate(evidence))
    questions = "\n".join(f"{n}. {q}" for n, q in JUDGED.items())

    try:
        answer = asyncio.run(_ask(questions, numbered))
    except Exception as exc:  # noqa: BLE001 - any provider or parse failure lands here
        log.warning("flag judgement failed (%s); withholding all six", type(exc).__name__)
        return [
            Judged(n, q, "UNKNOWN", None, "", None, "the model could not be reached")
            for n, q in JUDGED.items()
        ]

    by_number = {}
    for row in answer.get("flags", []):
        try:
            number = int(row.get("number"))
        except (TypeError, ValueError):
            continue
        # ⚠ A verdict on a computed flag is dropped on the floor. Those are measured, and a
        # measurable thing is never a matter of opinion.
        if number in JUDGED:
            by_number[number] = row

    return [_settle(n, by_number.get(n, {}), evidence, verify=verify) for n in sorted(JUDGED)]


# --- putting the ten together ----------------------------------------------------------------


@dataclass(frozen=True)
class Checklist:
    """All ten flags, and the band the framework's own notes put them in."""

    flags: list[Flag]
    red: int
    unknown: int

    @property
    def band(self) -> str:
        """⚠ The framework's own bands, from the notes: 0–3 low, 4–6 moderate, 7–10 high."""
        if self.red <= 3:
            return "Low risk"
        if self.red <= 6:
            return "Moderate risk"
        return "High speculative risk"

    @property
    def is_readable(self) -> bool:
        """⚠ False when most of the checklist is unanswered. Four YES out of four answered is
        not the same as four out of ten, and a band computed over two known flags would read
        exactly like one computed over all of them."""
        return self.unknown <= len(self.flags) // 2


def checklist(computed: list[Flag], judged: list[Judged]) -> Checklist:
    """Merge the measured and the judged. ⚠ Measured always wins."""
    measured = {flag.number: flag for flag in computed}
    merged = dict(measured)
    for row in judged:
        if row.number in measured:
            continue
        merged[row.number] = row.as_flag()

    flags = [merged[n] for n in sorted(merged)]
    return Checklist(
        flags=flags,
        red=sum(1 for f in flags if f.verdict in COUNTS_AS_RED),
        unknown=sum(1 for f in flags if f.verdict == "UNKNOWN"),
    )


def soros_score(flags: list[Flag], loop_direction: str | None) -> Decimal | None:
    """Signed reflexivity: +1 per Soros YES when the loop runs up, −1 when down or inverted.

    ⚠ The sign is the whole point and it is not obvious. An inverted loop — a negative
    narrative over an intact business, which is HDFC Bank's exact situation — scores
    *negatively* on reflexivity while remaining a perfectly good buy. A design that took the
    magnitude alone would have made the most interesting case in the portfolio unreadable.
    """
    if loop_direction is None:
        return None
    soros = [f for f in flags if f.number in (6, 7, 8, 9, 10) and f.verdict in COUNTS_AS_RED]
    sign = 1 if loop_direction.upper() == "UP" else -1
    return Decimal(sign * len(soros))
