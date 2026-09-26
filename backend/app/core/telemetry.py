"""Per-request timing and context accounting.

Answers, with measured numbers rather than guesses: what exactly went into this
request, how big each part was, and where the wall-clock time went. One line per turn
at INFO, so you can watch it live (`docker compose logs -f api`, or the uvicorn console)
and compare it against a stopwatch.

Token counts: the provider's own usage numbers are authoritative and are reported when
it returns them. `approx_tokens` is only a *local estimate* for the per-block breakdown
(a provider never tells you how many tokens the persona alone cost), and is labelled as
approximate wherever it is shown.
"""

import datetime as dt
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi.concurrency import run_in_threadpool

from app.core import pricing
from app.db.models import Span, Turn
from app.db.session import SessionLocal

log = logging.getLogger("aceroai.timing")
persist_log = logging.getLogger(__name__)

#: Who a model call made deep inside a service is on behalf of.
#:
#: ⚠ **Background model calls had nowhere to send their bill.** Chat knows its user because the
#: request carries one; a service function five calls below a scheduled job does not, so every
#: model call in the investments module — placing a company, reading a stance, answering a
#: checklist question twice, transliterating a Hindi transcript — ran without recording what it
#: cost. The Insights page under-reported spend, and the monthly budget could not stop what it
#: could not see.
#:
#: The job runner sets this for the duration of a job; a service reads it. A context variable
#: rather than a parameter because the alternative is threading a user id through a dozen
#: signatures that have no other use for one, and the first one forgotten is a silent leak.
billed_user: ContextVar[uuid.UUID | None] = ContextVar("billed_user", default=None)


@contextmanager
def billing(user_id: uuid.UUID):
    """Attribute every model call inside this block to `user_id`."""
    token = billed_user.set(user_id)
    try:
        yield
    finally:
        billed_user.reset(token)


# Rough bytes-per-token for English prose. Real tokenizers differ per model; this is a
# sizing aid for the context breakdown, never billing.
_CHARS_PER_TOKEN = 4


def approx_tokens(text: str) -> int:
    return max(1, round(len(text) / _CHARS_PER_TOKEN)) if text else 0


class Timeline:
    """Records how long each stage of one turn took, in order."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        # perf_counter has no relation to wall time, so a real timestamp is kept for the
        # stored trace — you cannot chart "spend in March" against a monotonic counter.
        self.started_at = dt.datetime.now(dt.UTC)
        self.stages: list[tuple[str, float]] = []
        self.notes: dict[str, object] = {}
        self.span_meta: dict[str, dict] = {}

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages.append((name, (time.perf_counter() - start) * 1000))

    def mark(self, name: str) -> None:
        """Record a moment measured from the start of the turn (e.g. first token)."""
        self.stages.append((name, (time.perf_counter() - self.t0) * 1000))

    def note(self, **kwargs: object) -> None:
        self.notes.update(kwargs)

    def annotate(self, stage: str, **meta: object) -> None:
        """Attach counts to a stage — retries, facts recalled, duplicates discarded.

        These are signals that were previously logged and then lost. Counting them here
        makes questions like "how often does a retry happen?" answerable from data rather
        than from grepping."""
        self.span_meta.setdefault(stage, {}).update(meta)

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self.t0) * 1000

    def emit(self) -> None:
        parts = " ".join(f"{name}={ms:.0f}ms" for name, ms in self.stages)
        extra = " ".join(f"{k}={v}" for k, v in self.notes.items())
        log.info("turn total=%.0fms %s %s", self.total_ms, parts, extra)

    # --- persistence ----------------------------------------------------------------

    def persist(
        self,
        user_id: uuid.UUID,
        kind: str,
        *,
        session_id: uuid.UUID | None = None,
        channel: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        usage: dict | None = None,
        rounds: int | None = None,
        ok: bool = True,
        error_type: str | None = None,
    ) -> uuid.UUID | None:
        """Store this trace as one `turns` row plus one `spans` row per stage.

        MUST be called after the response is complete. Opens its own session and swallows
        every failure: an observability system that can slow down or break the thing it
        observes is worse than no observability system. Returns the turn id, or None if
        writing failed.

        Sync on purpose — callers in async code wrap it in `run_in_threadpool`, the same as
        every other DB touchpoint.
        """
        usage = usage or {}
        db = SessionLocal()
        try:
            turn = Turn(
                user_id=user_id,
                session_id=session_id,
                channel=channel,
                kind=kind,
                provider=provider,
                model=model,
                effort=effort or None,
                started_at=self.started_at,
                duration_ms=round(self.total_ms),
                ttft_ms=next(
                    (round(ms) for name, ms in self.stages if name == "first_token"), None
                ),
                rounds=rounds,
                tokens_in=usage.get("tokens_in"),
                tokens_out=usage.get("tokens_out"),
                tokens_thinking=usage.get("tokens_thinking"),
                tokens_cached=usage.get("tokens_cached"),
                cost_usd=pricing.estimate_cost(
                    provider,
                    model,
                    tokens_in=usage.get("tokens_in"),
                    tokens_out=usage.get("tokens_out"),
                    tokens_thinking=usage.get("tokens_thinking"),
                    tokens_cached=usage.get("tokens_cached"),
                    when=self.started_at,
                ),
                pricing_version=pricing.PRICING_VERSION,
                ok=ok,
                error_type=error_type,
            )
            db.add(turn)
            db.flush()
            for seq, (name, ms) in enumerate(self.stages):
                db.add(
                    Span(
                        turn_id=turn.id,
                        name=name,
                        seq=seq,
                        duration_ms=round(ms),
                        meta=self.span_meta.get(name) or None,
                    )
                )
            db.commit()
            return turn.id
        except Exception:
            persist_log.warning("failed to persist trace; the reply is unaffected", exc_info=True)
            db.rollback()
            return None
        finally:
            db.close()


async def record(tl: "Timeline", *args, **kwargs) -> None:
    """Persist a trace off the reply path, swallowing absolutely everything.

    `Timeline.persist` already guards its own database work, but that only covers failures
    it anticipated. This wrapper is the guarantee itself: no defect in trace recording —
    a bad column, a type error, a broken session — can reach the code that was producing a
    reply. Enforced by a test that replaces `persist` with a function that always raises.

    Every caller uses this rather than `persist` directly.

    Housekeeping used to run from here as well, at most once a local day, because this was
    the only place that reliably executed after a reply had already been delivered. Since
    migration 011 it is a scheduled job (`app/jobs/housekeeping.py`), which means it also
    runs on a day nobody sent a message — and no longer contends for locks with the requests
    it was hiding behind.
    """
    try:
        await run_in_threadpool(tl.persist, *args, **kwargs)
    except Exception:
        persist_log.warning("trace recording failed; the reply is unaffected", exc_info=True)


def describe_context(messages: list[dict]) -> dict:
    """Size each part of what we're about to send, so the cost is visible per block."""
    blocks: list[dict] = []
    for m in messages:
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        blocks.append(
            {"role": m.get("role"), "chars": len(content), "approx_tokens": approx_tokens(content)}
        )
    return {
        "messages": len(messages),
        "chars": sum(b["chars"] for b in blocks),
        "approx_tokens": sum(b["approx_tokens"] for b in blocks),
        "blocks": blocks,
    }
