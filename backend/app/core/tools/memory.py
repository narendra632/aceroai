"""Memory tools: the assistant writing to memory *on purpose*, because the user said so.

Until now the only way a fact reached memory was the background extractor — a second model
reading the finished turn and guessing what was durable. That produced this exchange:

    user: remember that I have the AI-901 certification
    assistant: Got it, I've stored that.        <- it had stored nothing
    user: do I have AI-901?
    assistant: I don't have that in my memory.

Two separate defects. The assistant had no way to write, and it reported a write it had not
made. Both are addressed here: a tool that actually writes, and results that make a failure
impossible to narrate as a success.

**Why a tool here and JSON in the extractor.** A tool exists so a model can *choose to
act*, and choosing is exactly what the chat model does — it acts on maybe one message in a
hundred. The extractor has no such choice: it is handed a turn and asked "anything durable
here?" every single time, so tool-calling would buy it nothing and cost a second provider
round trip on every message. Its JSON is also checkable against a schema; a tool-call
transcript has to be interpreted.

**Ids come from context, not from a lookup tool.** Recalled facts are listed in the prompt
with their ids, exactly as open tasks already are, so correcting or forgetting is one step
rather than a search followed by a write. The limitation is honest and worth stating: a
fact that recall did not surface cannot be corrected by id in that turn. Hybrid recall is
what makes that rare — a message naming the fact ("forget that I like tea") now matches it
by word as well as by meaning.
"""

import uuid

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core import llm
from app.core.tools.common import parse_id
from app.services import memory as memory_svc
from app.services.memory import CATEGORIES

SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": (
                "Store a durable fact about the user in long-term memory. Use this when "
                "the user asks you to remember something, or tells you something stable "
                "and personal worth keeping (a preference, a goal, a relationship, "
                "something about their work or health). Do not use it for one-off "
                "logistics or anything you would not want to recall in six months."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": (
                            "A short third-person statement, phrased the same way as the "
                            "facts already in your context (e.g. 'Narendra has completed "
                            "the AI-901 certification.')."
                        ),
                    },
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "correct_fact",
            "description": (
                "Replace a stored fact with a corrected version, when the user tells you "
                "something you believe is wrong or out of date. The old version is kept "
                "as history, not deleted. Tell the user what you changed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_id": {
                        "type": "string",
                        "description": "The id of the fact to correct, from your context.",
                    },
                    "new_fact": {
                        "type": "string",
                        "description": "The corrected statement, in the same third-person style.",
                    },
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                },
                "required": ["fact_id", "new_fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_fact",
            "description": (
                "Forget a stored fact, when the user asks you to. Destructive — only on "
                "an explicit instruction, never on your own initiative. Say what you "
                "forgot in your reply."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_id": {
                        "type": "string",
                        "description": "The id of the fact to forget, from your context.",
                    }
                },
                "required": ["fact_id"],
            },
        },
    },
]


def _summary(fact) -> dict:
    return {"id": str(fact.id), "fact": fact.fact, "category": fact.category}


async def _remember_fact(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    """Embed, then write through the one writer.

    Async because embedding is a network call and a fact stored without a vector is
    invisible to recall — it would show on the Knowledge page while never informing a
    conversation again, which is a worse failure than refusing the write.
    """
    text = (a.get("fact") or "").strip()
    category = a.get("category") or "other"
    vectors = await llm.embed([text]) if text else [None]
    result = await run_in_threadpool(
        memory_svc.remember,
        db,
        user_id,
        text,
        category=category,
        embedding=vectors[0],
        # The user said it out loud. That is a statement, not an inference — and it is
        # what separates this from everything the background extractor writes.
        source="stated",
        confidence=1.0,
    )
    out = {"action": result.action, **_summary(result.fact)}
    if result.action == memory_svc.FLAGGED and result.related is not None:
        # Stored, but it resembles something already held. Surfaced rather than hidden so
        # the assistant can mention it — this is the branch that used to silently delete.
        out["resembles"] = _summary(result.related)
    if result.action == memory_svc.UNCHANGED:
        # Honest about doing nothing. "Stored" would be a lie, and an error would be wrong
        # too — the user's intent is satisfied, the sentence is already there verbatim.
        out["note"] = "already remembered, word for word — nothing was written"
    return out


async def _correct_fact(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    text = (a.get("new_fact") or "").strip()
    vectors = await llm.embed([text]) if text else [None]
    result = await run_in_threadpool(
        memory_svc.correct,
        db,
        user_id,
        parse_id(a["fact_id"]),
        text,
        embedding=vectors[0],
        category=a.get("category"),
    )
    out = {"action": result.action, **_summary(result.fact)}
    if result.related is not None:
        out["replaced"] = _summary(result.related)
    return out


def _forget_fact(db: Session, user_id: uuid.UUID, a: dict) -> dict:
    fact_id = parse_id(a["fact_id"])
    # Read it BEFORE forgetting, so the reply can name what went. "I've forgotten that"
    # is not something the user can check; "I've forgotten that you prefer tea" is.
    fact = memory_svc.get_fact(db, user_id, fact_id)
    summary = _summary(fact)
    memory_svc.forget_fact(db, user_id, fact_id)
    return {"action": "forgotten", **summary}


HANDLERS = {
    "remember_fact": _remember_fact,
    "correct_fact": _correct_fact,
    "forget_fact": _forget_fact,
}
