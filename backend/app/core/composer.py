"""Builds the model's input for a session: the SOUL.md persona as the system
message, followed by the session's recent messages in chronological order.

Later features extend this one function (profile facts, tasks); routes and
channels never change. This is where "what the model sees" is decided.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.recall import RecalledFact
from app.db.models import Message, User
from app.services import tasks as tasks_svc

# backend/app/core/composer.py -> parents[3] is the repo root.
_DEFAULT_SOUL_PATH = Path(__file__).resolve().parents[3] / "docs" / "SOUL.md"
HISTORY_LIMIT = 20

_FALLBACK_PERSONA = "You are Acero, a concise, warm personal assistant."


def _persona_path() -> Path:
    # In prod the image has no docs/, so the deploy sets SOUL_PATH to a mounted copy.
    return Path(settings.soul_path) if settings.soul_path else _DEFAULT_SOUL_PATH


def _read_persona() -> str:
    try:
        return _persona_path().read_text(encoding="utf-8").strip()
    except OSError:
        # last-resort fallback so chat never breaks on a missing persona file.
        return _FALLBACK_PERSONA


def _now_block() -> str:
    # Give the model the current date/time so it can resolve relative dates like
    # "Friday" or "tomorrow" when creating tasks.
    now = dt.datetime.now(ZoneInfo(settings.app_timezone))
    return f"Current date and time: {now:%A %Y-%m-%d %H:%M} ({settings.app_timezone})."


_PRIORITY_WORD = {1: "high", 2: "medium", 3: "low"}


def _tasks_block(db: Session, user: User) -> str | None:
    """The user's open tasks, so the assistant is *aware* rather than blind.

    Without this the model cannot see what already exists, so it creates duplicates,
    needs an extra round-trip to act on a task it was just told about, and can never
    proactively surface something that's due — which is a prime directive in SOUL.md.
    Ids are included so it can complete/update in a single step; the persona tells it
    not to read ids aloud.
    """
    rows = tasks_svc.list_tasks(db, user.id)[: settings.context_tasks_limit]
    if not rows:
        return "The user has no open tasks right now."
    now = dt.datetime.now(ZoneInfo(settings.app_timezone))
    lines = []
    for t in rows:
        bits = [f"[id {t.id}] {t.title}"]
        if t.due_at is not None:
            due = t.due_at.astimezone(ZoneInfo(settings.app_timezone))
            overdue = " OVERDUE" if due < now else ""
            bits.append(f"due {due:%a %d %b %H:%M}{overdue}")
        bits.append(f"{_PRIORITY_WORD.get(t.priority, 'medium')} priority")
        if t.status != "todo":
            bits.append(t.status)
        lines.append("- " + " — ".join(bits))
    return (
        "The user's open tasks, most urgent first. Use these instead of guessing: do "
        "not create a task that is already here (say it exists, or update it), and act "
        "on the right one by its id. Mention anything due or overdue when it is "
        "relevant.\n" + "\n".join(lines)
    )


#: What the Investments module is, in the words it uses about itself.
#:
#: ⚠ **Static, and that is deliberate.** Every figure comes from a tool, so nothing here can
#: go stale; what it supplies is the *vocabulary* and the handful of distinctions that are
#: easy to get wrong and expensive when got wrong. Without it the model reads "BLOCKED" as a
#: failure, "not yet" as "no", and "6 of 9" as mediocre — and answers confidently in each case.
#:
#: ⚠ It carries no numbers on purpose. A live summary here would be one more place the book's
#: figures are computed, and the page and the chat would eventually disagree about the same
#: portfolio. The tools are the single source, the same ones the page calls.
_INVESTMENTS_BLOCK = """\
The user runs an Investments module in this app. It is not a trading tool — it exists to keep
a written, timestamped, unchangeable record of WHY each decision was made, and to grade that
reasoning later. Use the investment tools for anything about money, holdings, companies,
suggestions or performance rather than answering from memory.

How it is built, and the distinctions that matter when you speak about it:

- The LEDGER is the user's own word and a machine never writes to it. `record_transaction`
  returns a draft; only `confirm_transaction` writes. The same applies to a decision on a
  suggestion: `decide_suggestion` then `confirm_decision`.
- SCORES are two numbers that must always be quoted together — "6 of 9", never "6". Six of
  six is excellent and six of ten is mediocre, and the difference is only how much has been
  read.
- A component reads three ways and they are three different facts: a NUMBER was measured;
  "not read" means the filings are not in yet; "does not apply" means the test never
  described this kind of company — return on capital for a bank — and is not a gap anyone can
  fill. Never flatten the last two together.
- BLOCKED is the normal outcome and usually means the rules worked. Most suggestions are
  refused by the margin-of-safety rule, which says the company is good and the price is not.
  A blocked suggestion was never offered and cannot be decided on.
- The four BOXES: Q1 supercharged compounder, Q2 reflexive bubble (never a buy), Q3 ignored
  compounder, Q4 structural value trap (never a buy). BORDERLINE means neither blessed nor
  blocked — usually too few years read, or a score sitting right on the line.
- PREDICTIONS (claims) are recorded when a thesis is formed, whether or not the gates let the
  idea through, and can never be edited afterwards. They are the point of the whole module.
- TRUST TIERS: filing (the company's own word), press, commentary. Evidence from commentary
  alone can never carry a suggestion — the sourcing gate refuses it whatever it said.
- The RESEARCH QUEUE holds companies a source named that the user does not follow. A line
  there is a lead, never a recommendation, and nothing in it has been bought.
- "not yet" is never "no". Several go/no-go criteria cannot be tested until enough time has
  passed, and reporting one of those as failed would call the experiment early.
- Money is exact. Quote the figures the tools return; never re-derive, round or estimate one.
- The PAGE has six tabs, and naming the right one is how you point the user somewhere:
  Holdings (what is owned and what it is worth), Decisions (suggestions, fired conditions and
  leads worth a look), Companies (where each followed company sits in the framework, its
  scores and red flags — and where a company with no place is placed, by hand or by asking
  for a suggestion, and then agreed with), Sources (what is read, and adding a channel),
  Scorecard (whether any of it is working) and Records (every transaction, and Schedule FA).
  A list at the top of the page says what is waiting for the user.

Say what is missing as readily as what is known. A figure that excludes unpriced holdings, a
score resting on one year, a benchmark measured over a different window — each has to be said
out loud, because the tools report it and a reader who is not told will assume otherwise."""


def _facts_block(facts: Sequence[RecalledFact]) -> str:
    """The recalled facts, each with its id.

    Ids are here for the same reason they are on tasks: so correcting or forgetting a fact
    is one step instead of a search followed by a write. The persona tells the model not to
    read them aloud. They cost ~12 tokens per fact, which is the price of `correct_fact`
    and `forget_fact` working at all.
    """
    lines = "\n".join(f"- [id {f.id}] {f.fact}" for f in facts)
    return (
        "What you know about the user, recalled from earlier conversations (most relevant "
        "first). Use these ids with correct_fact / forget_fact when the user tells you one "
        f"of them is wrong or should be forgotten:\n{lines}"
    )


def build_context(
    db: Session,
    session_id: uuid.UUID,
    facts: Sequence[RecalledFact] | None = None,
    user: User | None = None,
) -> list[dict]:
    """Assemble model input: SOUL.md persona, the current date/time, the user's open
    tasks, the semantically-recalled profile facts (when any), then the session's
    recent messages in order.

    `facts` are recalled by the handler (an async embedding step) and passed in;
    tasks are a plain DB read, so they are loaded here. This stays fully synchronous.
    """
    rows = (
        db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_LIMIT)
        )
        .scalars()
        .all()
    )
    context: list[dict] = [
        {"role": "system", "content": _read_persona()},
        {"role": "system", "content": _now_block()},
        {"role": "system", "content": _INVESTMENTS_BLOCK},
    ]
    if user is not None:
        block = _tasks_block(db, user)
        if block:
            context.append({"role": "system", "content": block})
    if facts:
        context.append({"role": "system", "content": _facts_block(facts)})
    for m in reversed(rows):
        if m.role in ("user", "assistant"):
            context.append({"role": m.role, "content": m.content})
    return context
