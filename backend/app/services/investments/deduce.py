"""Working out which bottleneck a company solves.

⚠ **This is the one thing here a model is allowed to decide, and it is allowed to decide it
because it is not a number.** Which of India's structural chokepoints a business addresses is
a judgement about what the business *is* — the kind of reading a person does from a company's
own description of itself. Every figure that follows from it (how many imperatives that
bottleneck crosses, whether it is crisis-accelerated, what multiple is defensible) is copied
from the framework, not invented per company.

⚠ **The model chooses from a closed list; it cannot write one.** The answer is matched back
against the framework's own bottleneck IDs and anything unrecognised becomes *no mapping*,
which scores zero rather than guessing. A model free to name a bottleneck would be free to
invent a reason any company is nationally strategic, and that reason would read exactly like
a real one.

⚠ **And the answer is a PROPOSAL.** It scores nothing until a person agrees with it — the same
rule that has governed every mapping since the framework was installed. A claim about national
importance is worth nothing until a human accepts it, and that rule has no exception for
claims that arrived with a confident tone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from app.services import budget
from app.services.investments import billing

log = logging.getLogger(__name__)

#: ⚠ Low effort on purpose. This is a classification against a list of 31 options from a
#: company description — not an argument — and spending a frontier-model call on it would buy
#: nothing measurable while multiplying the cost of every candidate.
EFFORT = "low"

#: How sure the model has to be before the mapping is even proposed. Below this the candidate
#: is left unmapped, which is an honest state: the framework says "I do not know where this
#: sits", and an unmapped company simply scores zero structurally.
MIN_CONFIDENCE = 0.5

_PROMPT = """You are placing a company inside a framework of India's structural bottlenecks.

You will be given a company's name and what is known about it, then a numbered list of
bottlenecks. Decide which ONE bottleneck this company most directly helps solve.

Rules:
- Answer with an id from the list and nothing else. Never invent an id.
- "Most directly" means the company's actual revenue comes from solving it, not that it
  benefits from it happening. A bank that lends to solar developers is not solving solar
  manufacturing.
- If no bottleneck fits the company's actual business, answer with id "NONE". That is a real
  and common answer: most listed companies are ordinary businesses that this framework is not
  about, and forcing a fit is how a random small-cap becomes "nationally strategic".
- confidence is how sure you are, 0 to 1. Below 0.5 the answer is discarded, so use it.

Reply with JSON only:
{"id": "B1.1", "confidence": 0.8, "why": "one sentence, naming what the company actually sells"}"""


@dataclass(frozen=True)
class Deduction:
    """Where the model thinks a company sits, before anyone has agreed."""

    bottleneck_id: str | None
    confidence: float
    why: str

    @property
    def is_usable(self) -> bool:
        return self.bottleneck_id is not None and self.confidence >= MIN_CONFIDENCE


def _catalogue(spec: dict) -> str:
    lines = []
    for row in spec.get("bottlenecks", ()):
        crossings = row.get("crossings") or row.get("crosses") or ""
        lines.append(
            f"{row['id']}: {row.get('name', '')} {f'(crosses {crossings})' if crossings else ''}"
        )
    return "\n".join(lines)


async def _ask(name: str, about: str, spec: dict) -> dict:
    reply = await billing.complete(
        [
            {"role": "system", "content": _PROMPT},
            {
                "role": "user",
                "content": (
                    f"Company: {name}\n\nWhat is known about it:\n{about}\n\n"
                    f"Bottlenecks:\n{_catalogue(spec)}"
                ),
            },
        ],
        effort=EFFORT,
        purpose="place",
    )
    body = reply[reply.find("{") : reply.rfind("}") + 1]
    return json.loads(body)


def bottleneck_for(name: str, about: str, spec: dict) -> Deduction:
    """Which bottleneck this company solves, as far as the model can tell.

    ⚠ The returned id is **always** one the framework already knows, or `None`. The check is
    not a formality: it is the only thing standing between "the model reads a description" and
    "the model invents a reason a company is nationally strategic".
    """
    known = {row["id"] for row in spec.get("bottlenecks", ())}
    try:
        answer = _run(name, about, spec)
    except budget.BudgetExceeded:
        # ⚠ Named, not folded into "could not be reached". The two need different fixes, and a
        # person told the model was down would try again tomorrow and be refused again.
        return Deduction(None, 0.0, "this month's model budget is spent, so nothing was asked")
    except Exception as exc:  # noqa: BLE001 - any provider or parse failure lands here
        log.warning("bottleneck deduction failed (%s); leaving it unmapped", type(exc).__name__)
        return Deduction(None, 0.0, "the model could not be reached")

    raw = str(answer.get("id", "")).strip().upper()
    confidence = _as_float(answer.get("confidence"))
    why = str(answer.get("why", "")).strip()[:500]

    if raw in ("", "NONE", "NULL"):
        return Deduction(None, confidence, why or "no bottleneck fits this company's business")
    if raw not in known:
        # ⚠ Not an error and not a retry. An id outside the framework is exactly what this
        # check exists to catch, and the honest result is no mapping.
        log.warning("bottleneck deduction returned unknown id %r; leaving it unmapped", raw)
        return Deduction(None, 0.0, f"the model named {raw}, which is not in the framework")
    return Deduction(raw, confidence, why)


def _run(name: str, about: str, spec: dict) -> dict:
    # Sync callers (jobs, the API) have no event loop of their own, so `asyncio.run` is
    # correct here rather than a borrowed loop — the same pattern the digests use.
    return asyncio.run(_ask(name, about, spec))


def _as_float(value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(parsed, 0.0), 1.0)


def describe(name: str, excerpts: list[str]) -> str:
    """What is known about a company, for the model to read.

    ⚠ Only what sources actually said, never a summary of it. The description is evidence, and
    a paraphrase of evidence is not evidence — if the mapping later looks wrong, the words that
    produced it have to still be there to check against.
    """
    seen: list[str] = []
    for excerpt in excerpts:
        cleaned = re.sub(r"\s+", " ", excerpt or "").strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    if not seen:
        return f"Nothing beyond the name {name}."
    return "\n".join(f"- {line[:400]}" for line in seen[:6])
