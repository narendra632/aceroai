"""The one brain. Every conversational message, from any channel, flows through
`handle_message`. Routes and channel adapters are pure transport (golden rule 1).

The route is async (it streams); the DB is sync. So DB work happens only before
the stream (persist the user turn) and after it (persist the assistant turn),
each wrapped in `run_in_threadpool` — the event loop is never blocked, and the
DB is never touched mid-stream.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core import composer, llm, memory, telemetry, tools
from app.core.providers.base import BillingError, RateLimitError, add_usage
from app.db.models import ChatSession, Message, User
from app.services import user_settings

log = logging.getLogger(__name__)

TITLE_MAX = 60

# Hold references to background extraction tasks so they aren't garbage-collected
# before they finish (asyncio only keeps weak references to running tasks).
_bg_tasks: set[asyncio.Task] = set()


def _user_error(exc: Exception) -> str:
    """Map a provider exception to a safe, friendly message describing the *cause*.
    Full detail is logged server-side; raw provider text is never sent to the client.

    Billing and rate limits are reported separately on purpose: providers return the
    same status code for both, and calling an unpaid balance a "rate limit" sends you
    hunting for a limit that doesn't exist.
    """
    if isinstance(exc, BillingError):
        return (
            "The model provider rejected the request — this usually means a billing or "
            "quota problem on the provider account, not a temporary limit. "
            "Check the provider's billing/credits."
        )
    if isinstance(exc, RateLimitError):
        return "I've hit the model's rate limit for now — please try again in a little while."
    return "Something went wrong reaching the model. Please try again."


def _schedule_extraction(
    user_id: uuid.UUID,
    user_text: str,
    reply_text: str,
    known: list[str],
    source_ref: uuid.UUID | None,
) -> None:
    try:
        task = asyncio.create_task(
            memory.extract_and_store(
                user_id, user_text, reply_text, known=known, source_ref=source_ref
            )
        )
    except RuntimeError:  # no running loop (shouldn't happen from the async handler)
        return
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


def _title_from(text: str) -> str:
    title = " ".join(text.split())
    return title[:TITLE_MAX] if title else "New chat"


def _assistant_tool_message(content: str, tool_calls: list[dict]) -> dict:
    """The assistant turn that requested tools, appended to the running messages so the
    model sees what it called alongside the results.

    `_provider_raw` carries the provider's own representation of that turn when it has
    one (Gemini attaches a `thought_signature` to each call that must come back
    unchanged, or the follow-up turn is rejected). Providers that don't need it ignore
    the field.
    """
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": c["arguments"]},
            }
            for c in tool_calls
        ],
        "_provider_raw": next((c.get("raw") for c in tool_calls if c.get("raw") is not None), None),
    }


def _decode_args(raw: str) -> dict | None:
    """Parse a tool call's argument string; None signals malformed JSON so the loop
    can report it back to the model instead of executing anything."""
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else {}


def _persist_user_turn(
    db: Session, user: User, text: str, channel: str, session_id: uuid.UUID | None
) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns `(session_id, user_message_id)`.

    The message id is returned so a fact learned from this turn can record where it came
    from — provenance the user can follow back to the conversation.
    """
    if session_id is not None:
        session = db.get(ChatSession, session_id)
        if session is None or session.user_id != user.id:
            raise ValueError("session not found")
    else:
        session = ChatSession(user_id=user.id, channel=channel, title=_title_from(text))
        db.add(session)
        db.flush()
    message = Message(session_id=session.id, role="user", content=text)
    db.add(message)
    session.last_active_at = func.now()
    db.commit()
    return session.id, message.id


def _persist_assistant_turn(
    db: Session, session_id: uuid.UUID, content: str, model: str, usage: dict
) -> uuid.UUID:
    msg = Message(
        session_id=session_id,
        role="assistant",
        content=content,
        model=model,
        tokens_in=usage.get("tokens_in"),
        tokens_out=usage.get("tokens_out"),
    )
    db.add(msg)
    session = db.get(ChatSession, session_id)
    if session is not None:
        session.last_active_at = func.now()
    db.commit()
    return msg.id


async def handle_message(
    db: Session,
    user: User,
    text: str,
    channel: str,
    session_id: uuid.UUID | None = None,
    reasoning_effort: str | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Yield (event, data) pairs: one `session`, many `delta`, then `done`
    (or a single `error`). The transport layer decides how to render them.

    `reasoning_effort` is the adaptive-reasoning hook: a caller (a channel acting
    on explicit user intent, or a future task like the daily review) may pass a
    specific effort; otherwise chat defaults to `settings.reasoning_effort_chat`.

    The provider and model come from the user's saved settings (falling back to the
    server defaults). Because that resolution happens here in the one brain, every
    channel honors the same choice with no channel-specific code.
    """
    effort = reasoning_effort if reasoning_effort is not None else settings.reasoning_effort_chat
    deep = effort == settings.reasoning_effort_deep
    provider, model = user_settings.resolve(user, deep=deep)
    text = text or ""
    if len(text) > settings.max_input_chars:
        yield "error", f"That message is too long (max {settings.max_input_chars} characters)."
        return

    # Measured, not guessed: every stage below is timed and logged as one line per
    # turn (logger "aceroai.timing"), so latency can be checked against a stopwatch.
    tl = telemetry.Timeline()
    tl.note(provider=provider, model=model, effort=effort or "-", channel=channel)

    with tl.stage("persist_user"):
        session_id, user_message_id = await run_in_threadpool(
            _persist_user_turn, db, user, text, channel, session_id
        )
    yield "session", str(session_id)

    # Semantic recall (best-effort): the most relevant facts about the user for
    # this message, injected into context. A failure here never blocks the reply.
    # This is a *network* call (embedding) plus a pgvector search — usually the second
    # biggest cost after the model itself.
    with tl.stage("memory_recall"):
        facts = await memory.recall(db, user, text)
    with tl.stage("build_context"):
        context = await run_in_threadpool(composer.build_context, db, session_id, facts, user)
    shape = telemetry.describe_context(context)
    tl.note(
        facts=len(facts),
        ctx_msgs=shape["messages"],
        ctx_chars=shape["chars"],
        ctx_approx_tokens=shape["approx_tokens"],
    )
    log.debug("context blocks for session %s: %s", session_id, shape["blocks"])

    # Bounded tool-use loop (the "one brain" acting): the model may answer directly
    # (streamed text, unchanged for normal chat) or call tools, which we run via the
    # service layer and feed back until it produces a final answer. A `tool` event
    # lets the UI show a brief "working…" state. The loop is capped and every tool
    # result is fault-tolerant, so a turn always resolves.
    usage: dict = {}
    parts: list[str] = []
    messages = list(context)
    first_token_seen = False
    rounds = 0
    try:
        for _round in range(settings.tools_max_iters):
            rounds += 1
            round_start = time.perf_counter()
            round_text: list[str] = []
            tool_calls: list[dict] | None = None
            # A FRESH dict per round, folded into the turn's total below. Reusing one dict
            # across rounds is what made every tool-using turn under-report: providers
            # assign a cumulative total per request, so round 3 simply overwrote rounds 1
            # and 2 and the recorded cost was the last round alone.
            round_usage: dict = {}
            async for kind, payload in llm.stream_with_tools(
                messages,
                tools=tools.TOOLS,
                model=model,
                usage=round_usage,
                effort=effort,
                provider=provider,
            ):
                if kind == "delta":
                    if not first_token_seen:
                        first_token_seen = True
                        # The number the user actually feels: request in -> first word out.
                        tl.mark("first_token")
                    round_text.append(payload)
                    parts.append(payload)
                    yield "delta", payload
                else:  # "tool_calls" — end of this round
                    tool_calls = payload
            add_usage(usage, round_usage)
            tl.stages.append((f"llm_round{rounds}", (time.perf_counter() - round_start) * 1000))
            if not tool_calls:
                break  # the model answered; done
            messages.append(_assistant_tool_message("".join(round_text), tool_calls))
            for call in tool_calls:
                yield "tool", call["name"]
                args = _decode_args(call["arguments"])
                if args is None:
                    result: dict = {"ok": False, "error": "arguments were not valid JSON"}
                else:
                    with tl.stage(f"tool:{call['name']}"):
                        result = await run_in_threadpool(
                            tools.execute, db, user.id, call["name"], args
                        )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        # Gemini pairs a response to its call by name, so always send it.
                        "name": call["name"],
                        "content": json.dumps(result),
                    }
                )
        else:
            # Hit the round cap while still calling tools: force a final text answer
            # (no tools) so the turn never ends mid-action.
            final_usage: dict = {}
            async for kind, payload in llm.stream_with_tools(
                messages,
                tools=None,
                model=model,
                usage=final_usage,
                effort=effort,
                provider=provider,
            ):
                if kind == "delta":
                    parts.append(payload)
                    yield "delta", payload
            add_usage(usage, final_usage)
    except Exception as exc:  # noqa: BLE001 - one place to catch any provider failure
        log.warning("generation failed for session %s", session_id, exc_info=True)
        tl.note(error=type(exc).__name__)
        tl.emit()
        yield "error", _user_error(exc)
        return

    reply = "".join(parts)
    with tl.stage("persist_assistant"):
        message_id = await run_in_threadpool(
            _persist_assistant_turn, db, session_id, reply, f"{provider}/{model}", usage
        )
    yield "done", str(message_id)

    # Provider-reported token usage is authoritative; the ctx_* numbers above are our
    # own estimate of what each block contributed.
    tl.note(
        rounds=rounds,
        reply_chars=len(reply),
        tokens_in=usage.get("tokens_in", "-"),
        tokens_out=usage.get("tokens_out", "-"),
    )
    tl.emit()

    # Learn durable facts from this turn, off the reply path — deliberately AFTER
    # "done", so its latency is never felt by the user.
    #
    # `facts` is handed straight to the extractor: recall already embedded this message and
    # retrieved the facts most related to it, which are exactly the ones a new fact might
    # duplicate. Reusing them costs nothing and keeps the extraction prompt a fixed size
    # instead of one that grows with everything ever learned.
    if settings.memory_extraction_enabled and reply:
        _schedule_extraction(user.id, text, reply, facts, user_message_id)
